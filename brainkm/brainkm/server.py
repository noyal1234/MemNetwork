"""MCP stdio server entry — tools for Cursor integration."""

from __future__ import annotations

import json
from pathlib import Path

import anyio
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import Tool

from brainkm import __version__
from brainkm.config import get_settings
from brainkm.db.migrate import migrate
from brainkm.logging_config import get_logger
from brainkm.models.schemas import (
    BrainStatsRequest,
    ContextPackRequest,
    ForgetRequest,
    GraphSyncRequest,
    RecallRequest,
    RememberRequest,
    SessionStatusRequest,
    TraverseRequest,
)
from brainkm.services.config_loader import load_brain_config
from brainkm.services.graphify_sync import start_graph_sync_scheduler, stop_graph_sync_scheduler
from brainkm.services.write_queue import get_write_queue
from brainkm.tools.dispatch import BrainRuntime, dispatch_tool

logger = get_logger("server")

TOOL_DEFINITIONS: list[tuple[str, str, type]] = [
    ("remember", "Store a project neuron (decision, fact, rule). Input is redacted before storage.", RememberRequest),
    ("recall", "FTS5 + 2-hop graph recall from live brain.db. Abstains on low confidence.", RecallRequest),
    (
        "context_pack",
        (
            "Compile a bounded task pack (neurons + code neighborhood + procedures). "
            "Include a symbol or file path in the query (or seed_refs) so the AST graph "
            "neighborhood can be seeded. Prefer before reading 3+ source files."
        ),
        ContextPackRequest,
    ),
    ("session_status", "Read or write the current session context neuron.", SessionStatusRequest),
    (
        "traverse",
        (
            "Explicit 1–2 hop AST graph traversal (calls/imports/defines). "
            "Use before editing shared code to see callers/importers and flow impact."
        ),
        TraverseRequest,
    ),
    ("forget", "Soft-archive a neuron (sets valid_until via audit_log).", ForgetRequest),
    (
        "brain_stats",
        (
            "Brain health summary: neuron/graph counts, last graph import, staleness, "
            "review queue size, abstention calibration. Use before trusting traverse/context_pack."
        ),
        BrainStatsRequest,
    ),
    (
        "graph_sync",
        (
            "Refresh the code graph (queue or force extract+import). "
            "Use when brain_stats reports a stale graph or after large refactors."
        ),
        GraphSyncRequest,
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
        return [
            Tool(
                name=name,
                description=description,
                inputSchema=_tool_schema(model),
            )
            for name, description, model in TOOL_DEFINITIONS
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict | None):
        from mcp.types import TextContent

        try:
            payload = await dispatch_tool(name, arguments or {}, runtime)
        except Exception as exc:
            logger.exception("tool=%s failed", name)
            payload = {"error": str(exc), "tool": name}
        return [
            TextContent(
                type="text",
                text=json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
            )
        ]

    return server


async def run_stdio_server(project_dir: Path | None = None) -> None:
    settings = get_settings()
    root = (project_dir if project_dir is not None else settings.project_dir).resolve()

    migrate(project_dir=root, run_integrity_check=True)
    brain_config = load_brain_config(root)
    runtime = BrainRuntime(project_dir=root)
    server = create_server(runtime)
    queue = get_write_queue()
    await queue.start()
    start_graph_sync_scheduler(root, brain_config)

    logger.info("brainkm MCP server starting project_dir=%s", root)
    try:
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
    finally:
        stop_graph_sync_scheduler()
        await queue.stop()


def main(project_dir: Path | None = None) -> None:
    anyio.run(run_stdio_server, project_dir)
