"""MCP transport: structuredContent required when outputSchema is set."""

from __future__ import annotations

import asyncio
from pathlib import Path

from mcp import types

from brainkm.db.migrate import migrate
from brainkm.server import create_server
from brainkm.services.write_queue import WriteQueue
from brainkm.tools.dispatch import BrainRuntime


def test_call_tool_returns_structured_content(tmp_path: Path) -> None:
    async def _run() -> None:
        migrate(project_dir=tmp_path, run_integrity_check=False)
        runtime = BrainRuntime(project_dir=tmp_path)
        server = create_server(runtime)
        import brainkm.services.write_queue as wq_mod

        queue = WriteQueue()
        prev = wq_mod._write_queue
        wq_mod._write_queue = queue
        await queue.start()
        try:
            handler = server.request_handlers[types.CallToolRequest]
            req = types.CallToolRequest(
                params=types.CallToolRequestParams(name="brain_stats", arguments={})
            )
            result = await handler(req)
            assert isinstance(result.root, types.CallToolResult)
            assert result.root.isError is False
            assert result.root.structuredContent is not None
            assert "neurons_by_kind" in result.root.structuredContent
            assert result.root.content
        finally:
            await queue.stop()
            wq_mod._write_queue = prev

    asyncio.run(_run())


def test_call_tool_error_is_error_without_schema_fail(tmp_path: Path) -> None:
    async def _run() -> None:
        migrate(project_dir=tmp_path, run_integrity_check=False)
        runtime = BrainRuntime(project_dir=tmp_path)
        server = create_server(runtime)
        handler = server.request_handlers[types.CallToolRequest]
        req = types.CallToolRequest(
            params=types.CallToolRequestParams(name="no_such_tool", arguments={})
        )
        result = await handler(req)
        assert isinstance(result.root, types.CallToolResult)
        assert result.root.isError is True
        assert result.root.structuredContent is None
        text = result.root.content[0].text
        assert "unknown tool" in text

    asyncio.run(_run())
