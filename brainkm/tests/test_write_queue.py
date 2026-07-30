"""Tests for the asyncio write queue."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from brainkm.db.connection import connect
from brainkm.db.migrate import migrate
from brainkm.services.write_queue import (
    WriteQueue,
    get_write_queue,
    reset_write_queue_for_tests,
    run_blocking,
)
from tests.conftest import insert_node


@pytest.mark.asyncio
async def test_write_queue_serializes_writes(brain_db) -> None:
    queue = WriteQueue()
    await queue.start()

    def write_node(node_id: str) -> int:
        conn = connect(brain_db)
        try:
            insert_node(conn, node_id=node_id, title=f"Node {node_id}")
            conn.commit()
            return conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        finally:
            conn.close()

    counts = await __import__("asyncio").gather(
        queue.run(write_node, "q1"),
        queue.run(write_node, "q2"),
        queue.run(write_node, "q3"),
    )
    assert counts[-1] == 3
    await queue.stop()


@pytest.mark.asyncio
async def test_write_queue_retries_on_busy(brain_db) -> None:
    queue = WriteQueue()
    await queue.start()

    attempts = {"count": 0}

    def flaky_write() -> str:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise sqlite3.OperationalError("database is locked")
        conn = connect(brain_db)
        try:
            insert_node(conn, node_id="retry-node", title="Retry me")
            conn.commit()
            return "ok"
        finally:
            conn.close()

    result = await queue.run(flaky_write)
    assert result == "ok"
    assert attempts["count"] == 2
    await queue.stop()


@pytest.mark.asyncio
async def test_start_resurrects_worker_after_loop_dies(brain_db) -> None:
    """A done/cross-loop worker must not block a later start on a new loop."""
    queue = WriteQueue()
    await queue.start()
    worker = queue._worker_task
    assert worker is not None
    await queue.stop()
    assert worker.done()
    # Simulate abandoned global state after an async pytest loop closed mid-flight:
    # leave a done task pointer instead of clearing it.
    queue._worker_task = worker

    await queue.start()
    assert queue._has_live_worker()
    assert queue._worker_task is not worker

    def write_once() -> str:
        conn = connect(brain_db)
        try:
            insert_node(conn, node_id="resurrect", title="ok")
            conn.commit()
            return "ok"
        finally:
            conn.close()

    assert await queue.run(write_once) == "ok"
    await queue.stop()


def test_run_blocking_survives_stale_global_worker(tmp_path: Path) -> None:
    """CLI ``run_blocking`` must not hang when MCP/async tests left a dead worker."""
    migrate(project_dir=tmp_path, run_integrity_check=False)
    reset_write_queue_for_tests()

    async def _poison_global() -> None:
        queue = get_write_queue()
        await queue.start()
        # Leave the task pointer set but stop consuming — mirrors a closed loop
        # where awaiting the old worker is impossible.
        task = queue._worker_task
        assert task is not None
        await queue._queue.put(None)
        await task
        # Intentionally leave _worker_task pointing at the finished task.

    asyncio.run(_poison_global())

    queue = get_write_queue()
    assert queue._worker_task is not None
    assert queue._worker_task.done()

    def _write() -> str:
        return "alive"

    assert run_blocking(_write) == "alive"
    reset_write_queue_for_tests()
