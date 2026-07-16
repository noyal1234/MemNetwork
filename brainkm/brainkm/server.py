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
    ForgetRequest,
    ForgetResponse,
    GraphSyncRequest,
    GraphSyncResponse,
    RecallRequest,
    RecallResponse,
    RememberRequest,
    RememberResponse,
    SessionStatusRequest,
    SessionStatusResponse,
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
        "Store a project neuron (decision, fact, rule). Input is redacted before storage.",
        RememberRequest,
        RememberResponse,
    ),
    (
        "recall",
        "Hybrid FTS5 + optional vector RRF + PPR graph recall. Abstains on low confidence.",
        RecallRequest,
        RecallResponse,
    ),
    (
        "context_pack",
        (
            "Compile a bounded task pack (neurons + code neighborhood + procedures). "
            "Include a symbol or file path in the query (or seed_refs) so the AST graph "
            "neighborhood can be seeded. Prefer before reading 3+ source files."
        ),
        ContextPackRequest,
        ContextPackResponse,
    ),
    (
        "session_status",
        "Read or write the current session context neuron.",
        SessionStatusRequest,
        SessionStatusResponse,
    ),
    (
        "traverse",
        (
            "Explicit 1–2 hop AST graph traversal (calls/imports/defines). "
            "Use before editing shared code to see callers/importers and flow impact."
        ),
        TraverseRequest,
        TraverseResponse,
    ),
    (
        "forget",
        "Soft-archive a neuron (sets valid_until via audit_log).",
        ForgetRequest,
        ForgetResponse,
    ),
    (
        "brain_stats",
        (
            "Brain health summary: neuron/graph counts, last graph import, staleness, "
            "review queue size, abstention calibration. Use before trusting traverse/context_pack."
        ),
        BrainStatsRequest,
        BrainStatsResponse,
    ),
    (
        "graph_sync",
        (
            "Refresh the code graph (queue or force extract+import). "
            "Use when brain_stats reports a stale graph or after large refactors."
        ),
        GraphSyncRequest,
        GraphSyncResponse,
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

    set_sampling_callback(_sampling_callback)


async def run_http_server(
    project_dir: Path | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    """Streamable HTTP transport — one server shared across local editors."""
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.routing import Mount

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

    manager = StreamableHTTPSessionManager(app=server, json_response=True, stateless=True)

    async def lifespan(app):  # noqa: ANN001, ARG001
        async with manager.run():
            yield

    starlette_app = Starlette(
        routes=[Mount("/mcp", app=manager.handle_request)],
        lifespan=lifespan,
    )

    import uvicorn

    config = uvicorn.Config(starlette_app, host=host, port=port, log_level="info")
    http_server = uvicorn.Server(config)
    logger.info("brainkm MCP HTTP listening on http://%s:%s/mcp", host, port)
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
) -> None:
    if http:

        async def _run() -> None:
            await run_http_server(project_dir, host=host, port=port)

        anyio.run(_run)
    else:
        anyio.run(run_stdio_server, project_dir)
