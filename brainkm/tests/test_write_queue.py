"""Tests for the asyncio write queue."""

import sqlite3

import pytest

from brainkm.db.connection import connect
from brainkm.services.write_queue import WriteQueue
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
