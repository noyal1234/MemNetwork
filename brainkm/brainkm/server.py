"""MCP stdio/HTTP server entry — tools + resources for agent clients."""

from __future__ import annotations

import json
from pathlib import Path

import anyio
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, Resource, TextContent, Tool

from brainkm import __version__
from brainkm.config import get_settings
from brainkm.db.connection import connect
from brainkm.db.migrate import migrate
from brainkm.db.paths import brain_db_path
from brainkm.logging_config import get_logger
from brainkm.models.schemas import (
    BrainStatsRequest,
    BrainStatsResponse,
    ContextPackRequest,
    ContextPackResponse,
    RecallRequest,
    RecallResponse,
    RememberRequest,
    RememberResponse,
    TraceChangesRequest,
    TraceChangesResponse,
    TraverseRequest,
    TraverseResponse,
)
from brainkm.services.config_loader import load_brain_config
from brainkm.services.graphify_sync import start_graph_sync_scheduler, stop_graph_sync_scheduler
from brainkm.services.write_queue import get_write_queue
from brainkm.tools.dispatch import BrainRuntime, dispatch_tool

logger = get_logger("server")

TOOL_DEFINITIONS: list[tuple[str, str, type, type]] = [
    (
        "remember",
        (
            "Pin durable project truth, correct a wrong auto-capture (action=correct + "
            "target_node_id writes a supersedes edge), or archive noise (action=archive). "
            "Hooks (not this tool) are the primary memory path — do not use for ordinary "
            "session notes."
        ),
        RememberRequest,
        RememberResponse,
    ),
    (
        "recall",
        (
            "Live project memory search (decisions, rules, errors) with optional "
            "decision_trail supersede history for why/history questions. Abstains on "
            "low confidence. Not for call graphs (traverse) or multi-file packs "
            "(context_pack)."
        ),
        RecallRequest,
        RecallResponse,
    ),
    (
        "context_pack",
        (
            "Compile a bounded task pack (decisions + code neighborhood + procedures). "
            "Prefer before reading 3+ source files — include a symbol or path "
            "(or seed_refs). Auto-queues graph refresh when stale. For pure "
            "call/import/blast-radius questions use traverse."
        ),
        ContextPackRequest,
        ContextPackResponse,
    ),
    (
        "traverse",
        (
            "Impact analysis: AST neighborhood (callers/callees/imports) plus "
            "impact_summary (hop counts, high fan-in risk) and linked decision/error "
            "neurons. Prefer for 'what breaks if I change Y?'. Not for decisions-only "
            "(recall) or multi-file task packs (context_pack)."
        ),
        TraverseRequest,
        TraverseResponse,
    ),
    (
        "brain_stats",
        (
            "Brain health summary: neuron/graph counts, last graph import, staleness, "
            "review queue, abstention calibration, hygiene hint. Use before trusting "
            "traverse/context_pack when results look empty."
        ),
        BrainStatsRequest,
        BrainStatsResponse,
    ),
    (
        "trace_changes",
        (
            "Change history for a file: live git log --follow (real commits/diffs stay "
            "in git) joined to brain commit↔session↔decision links from git-note. "
            "Includes an uncommitted section from working-tree git diff + file_seed. "
            "Prefer for 'what changed here recently and why?'. Not for AST blast-radius "
            "(traverse) or decisions-only (recall)."
        ),
        TraceChangesRequest,
        TraceChangesResponse,
    ),
]


def _tool_schema(model: type) -> dict[str, object]:
    schema = model.model_json_schema()
    schema.pop("title", None)
    return schema


def create_server(runtime: BrainRuntime) -> Server:
    server = Server("brainkm")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        tools: list[Tool] = []
        for name, description, request_model, response_model in TOOL_DEFINITIONS:
            tools.append(
                Tool(
                    name=name,
                    description=description,
                    inputSchema=_tool_schema(request_model),
                    outputSchema=_tool_schema(response_model),
                )
            )
        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict | None):
        # Return a dict so MCP SDK 1.28+ fills structuredContent (required when
        # outputSchema is set). Errors use CallToolResult(isError=True) to skip
        # outputSchema validation.
        try:
            return await dispatch_tool(name, arguments or {}, runtime)
        except Exception as exc:
            logger.exception("tool=%s failed", name)
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {"error": str(exc), "tool": name},
                            separators=(",", ":"),
                            ensure_ascii=False,
                        ),
                    )
                ],
                isError=True,
            )

    @server.list_resources()
    async def list_resources() -> list[Resource]:
        return [
            Resource(
                uri="brainkm://stats",
                name="brain_stats",
                description="Brain health summary JSON",
                mimeType="application/json",
            ),
            Resource(
                uri="brainkm://neurons",
                name="active_neurons",
                description="Active memory neurons (titles + ids)",
                mimeType="application/json",
            ),
        ]

    @server.read_resource()
    async def read_resource(uri: str) -> str:
        conn = connect(brain_db_path(runtime.project_dir))
        try:
            if str(uri) == "brainkm://stats":
                from brainkm.services.brain_stats import collect_brain_stats

                stats = collect_brain_stats(
                    conn,
                    config=runtime.config,
                    project_dir=runtime.project_dir,
                )
                return json.dumps(stats.model_dump(), indent=2)
            if str(uri) == "brainkm://neurons":
                rows = conn.execute(
                    """
                    SELECT id, subtype, title FROM nodes
                    WHERE kind = 'memory' AND valid_until IS NULL
                    ORDER BY updated_at DESC LIMIT 100
                    """
                ).fetchall()
                return json.dumps(
                    [{"id": r[0], "subtype": r[1], "title": r[2]} for r in rows],
                    indent=2,
                )
            return json.dumps({"error": f"unknown resource: {uri}"})
        finally:
            conn.close()

    return server


async def _serve(runtime: BrainRuntime, server: Server) -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="brainkm",
                server_version=__version__,
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


async def run_stdio_server(project_dir: Path | None = None) -> None:
    settings = get_settings()
    root = (project_dir if project_dir is not None else settings.project_dir).resolve()

    migrate(project_dir=root, run_integrity_check=True)
    brain_config = load_brain_config(root)
    runtime = BrainRuntime(project_dir=root)
    server = create_server(runtime)
    _register_sampling_callback(server)
    queue = get_write_queue()
    await queue.start()
    start_graph_sync_scheduler(root, brain_config)

    logger.info("brainkm MCP server starting (stdio) project_dir=%s", root)
    try:
        await _serve(runtime, server)
    finally:
        from brainkm.adapters.mcp_distill import clear_sampling_callback

        clear_sampling_callback()
        stop_graph_sync_scheduler()
        await queue.stop()


def _register_sampling_callback(server: Server) -> None:
    """Register MCP sampling distill hook.

    Capture/distill runs outside the MCP request task in most flows, so the
    default callback returns empty → rules fallback. Hosts/tests may call
    ``set_sampling_callback`` with a real sampler. When a request context with
    ``session.create_message`` is present, we attempt a best-effort sync bridge.
    """
    from brainkm.adapters.mcp_distill import clear_sampling_callback, set_sampling_callback

    clear_sampling_callback()
    _ = server  # reserved for future ContextVar-bound session

    def _sampling_callback(*, system: str, user: str, max_tokens: int = 2000) -> str:
        _ = (system, user, max_tokens)
        return ""

    # Stub is not live — ClaudeDistillAdapter will use ``claude -p`` instead.
    set_sampling_callback(_sampling_callback, live=False)


async def run_http_server(
    project_dir: Path | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    allow_remote: bool = False,
) -> None:
    """Streamable HTTP transport — one server shared across local editors."""
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Mount, Route

    from brainkm import __version__
    from brainkm.services.mcp_http_auth import (
        RemoteBindDeniedError,
        assert_bind_allowed,
        ensure_mcp_http_token,
        extract_bearer_token,
        token_matches,
    )

    settings = get_settings()
    root = (project_dir if project_dir is not None else settings.project_dir).resolve()
    migrate(project_dir=root, run_integrity_check=True)
    brain_config = load_brain_config(root)
    allow = allow_remote or brain_config.mcp.allow_remote
    try:
        assert_bind_allowed(host, allow_remote=allow)
    except RemoteBindDeniedError:
        raise
    http_token = ensure_mcp_http_token(root)

    runtime = BrainRuntime(project_dir=root)
    server = create_server(runtime)
    _register_sampling_callback(server)
    queue = get_write_queue()
    await queue.start()
    start_graph_sync_scheduler(root, brain_config)

    manager = StreamableHTTPSessionManager(app=server, json_response=True, stateless=True)

    async def lifespan(app):  # noqa: ANN001, ARG001
        async with manager.run():
            yield

    async def health(request: Request) -> JSONResponse:
        payload: dict[str, object] = {
            "ok": True,
            "version": __version__,
        }
        provided = extract_bearer_token(request.headers.get("Authorization"))
        if token_matches(provided, http_token):
            payload["project_dir"] = str(root)
        return JSONResponse(payload)

    class _McpBearerMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):  # noqa: ANN001
            path = request.url.path
            if path == "/mcp" or path.startswith("/mcp/"):
                provided = extract_bearer_token(request.headers.get("Authorization"))
                if not token_matches(provided, http_token):
                    return Response("Unauthorized", status_code=401, media_type="text/plain")
            return await call_next(request)

    starlette_app = Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Mount("/mcp", app=manager.handle_request),
        ],
        lifespan=lifespan,
    )
    starlette_app.add_middleware(_McpBearerMiddleware)

    import uvicorn

    config = uvicorn.Config(starlette_app, host=host, port=port, log_level="info")
    http_server = uvicorn.Server(config)
    logger.info(
        "brainkm MCP HTTP listening on http://%s:%s/mcp (bearer auth required)",
        host,
        port,
    )
    try:
        await http_server.serve()
    finally:
        from brainkm.adapters.mcp_distill import clear_sampling_callback

        clear_sampling_callback()
        stop_graph_sync_scheduler()
        await queue.stop()


def main(
    project_dir: Path | None = None,
    *,
    http: bool = False,
    host: str = "127.0.0.1",
    port: int = 8765,
    allow_remote: bool = False,
) -> None:
    if http:

        async def _run() -> None:
            await run_http_server(
                project_dir,
                host=host,
                port=port,
                allow_remote=allow_remote,
            )

        anyio.run(_run)
    else:
        anyio.run(run_stdio_server, project_dir)
