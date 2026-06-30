"""Tests for graph channel health and FTS fallback."""

from brainkm.db.connection import connect
from brainkm.models.brain_config import BrainConfig
from brainkm.services.channel_health import graph_available, latest_graph_import_status
from brainkm.services.context_pack import compile_context_pack
from tests.conftest import insert_node


def test_graph_available_false_when_no_import(brain_db) -> None:
    conn = connect(brain_db)
    try:
        assert graph_available(conn) is False
        assert latest_graph_import_status(conn) is None
    finally:
        conn.close()


def test_context_pack_fts_fallback_when_graph_missing(brain_db) -> None:
    conn = connect(brain_db)
    try:
        insert_node(
            conn,
            node_id="note",
            title="payments retry policy",
            content="Use exponential backoff",
        )
        conn.commit()

        pack = compile_context_pack(
            conn,
            "payments retry",
            config=BrainConfig(recall={"abstain_on_low_confidence": False}),
        )
        assert pack.graph_available is False
        assert "Graph unavailable" in pack.pack_text
        assert pack.neurons
    finally:
        conn.close()


def test_graph_available_true_after_completed_import(brain_db) -> None:
    conn = connect(brain_db)
    try:
        conn.execute(
            """
            INSERT INTO graph_import_runs (id, started_at, completed_at, status, node_count, edge_count)
            VALUES ('run1', '2026-01-01T00:00:00Z', '2026-01-01T00:00:01Z', 'completed', 1, 0)
            """
        )
        conn.commit()
        assert graph_available(conn) is True
        assert latest_graph_import_status(conn) == "completed"
    finally:
        conn.close()
