"""Tests for V2 procedure promotion helpers."""

from __future__ import annotations

from brainkm.db.connection import connect
from brainkm.models.brain_config import BrainConfig
from brainkm.services.learning import get_learning_window
from brainkm.services.procedures import check_and_promote, find_promotable_pairs, upsert_procedure_neuron
from tests.conftest import insert_edge, insert_node


def test_find_promotable_pairs_threshold(brain_db) -> None:
    conn = connect(brain_db)
    try:
        insert_node(conn, node_id="a", title="A")
        insert_node(conn, node_id="b", title="B")
        insert_edge(conn, edge_id="e1", from_id="a", to_id="b", relationship="co_activated", weight=3)
        conn.commit()
        assert find_promotable_pairs(conn, threshold=3) == [("a", "b")]
        assert find_promotable_pairs(conn, threshold=4) == []
    finally:
        conn.close()


def test_upsert_procedure_deduplicates(brain_db) -> None:
    conn = connect(brain_db)
    try:
        insert_node(conn, node_id="a", title="Auth")
        insert_node(conn, node_id="b", title="Middleware")
        conn.commit()
        first = upsert_procedure_neuron(
            conn,
            neuron_ids=["a", "b"],
            tool_names=["Edit", "Shell"],
            session_id="sess",
        )
        second = upsert_procedure_neuron(
            conn,
            neuron_ids=["a", "b"],
            tool_names=["Edit", "Shell"],
            session_id="sess",
        )
        conn.commit()
        assert first is not None
        assert second is None
        count = conn.execute(
            "SELECT COUNT(*) AS total FROM nodes WHERE kind = 'procedure'"
        ).fetchone()
        assert count["total"] == 1
    finally:
        conn.close()


def test_check_and_promote_creates_procedure(brain_db) -> None:
    conn = connect(brain_db)
    window = get_learning_window()
    window.reset()
    try:
        insert_node(conn, node_id="a", title="Auth")
        insert_node(conn, node_id="b", title="Token")
        insert_edge(conn, edge_id="e1", from_id="a", to_id="b", relationship="co_activated", weight=3)
        conn.commit()
        window.record_tool_use("sess", "Edit", {})
        window.record_tool_use("sess", "Shell", {})
        promoted = check_and_promote(conn, "sess", config=BrainConfig())
        conn.commit()
        assert len(promoted) == 1
    finally:
        window.reset()
        conn.close()
