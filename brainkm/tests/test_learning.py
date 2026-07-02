"""Tests for V2 learning window and co-activation edges."""

from __future__ import annotations

from brainkm.db.connection import connect
from brainkm.models.brain_config import BrainConfig
from brainkm.services.learning import get_learning_window, process_post_tool
from tests.conftest import insert_node


def test_co_activation_weight_increments(brain_db) -> None:
    conn = connect(brain_db)
    window = get_learning_window()
    window.reset()
    try:
        insert_node(conn, node_id="n1", title="one")
        insert_node(conn, node_id="n2", title="two")
        conn.commit()

        window.record_neuron_hits("s1", ["n1", "n2"])
        process_post_tool(conn, "s1", "Edit", {}, config=BrainConfig())
        process_post_tool(conn, "s1", "Shell", {}, config=BrainConfig())
        conn.commit()

        row = conn.execute(
            """
            SELECT weight FROM edges
            WHERE relationship = 'co_activated' AND from_id = 'n1' AND to_id = 'n2'
            """
        ).fetchone()
        assert row is not None
        assert int(row["weight"]) == 2
    finally:
        window.reset()
        conn.close()


def test_no_edge_created_for_single_neuron(brain_db) -> None:
    conn = connect(brain_db)
    window = get_learning_window()
    window.reset()
    try:
        insert_node(conn, node_id="solo", title="single")
        conn.commit()

        window.record_neuron_hits("s1", ["solo"])
        process_post_tool(conn, "s1", "Edit", {}, config=BrainConfig())
        conn.commit()

        count = conn.execute(
            "SELECT COUNT(*) AS total FROM edges WHERE relationship = 'co_activated'"
        ).fetchone()
        assert count["total"] == 0
    finally:
        window.reset()
        conn.close()


def test_canonical_edge_ordering(brain_db) -> None:
    conn = connect(brain_db)
    window = get_learning_window()
    window.reset()
    try:
        insert_node(conn, node_id="zeta", title="z")
        insert_node(conn, node_id="alpha", title="a")
        conn.commit()
        window.record_neuron_hits("s2", ["zeta", "alpha"])
        process_post_tool(conn, "s2", "Edit", {}, config=BrainConfig())
        conn.commit()
        row = conn.execute(
            """
            SELECT from_id, to_id FROM edges WHERE relationship = 'co_activated'
            """
        ).fetchone()
        assert row is not None
        assert row["from_id"] == "alpha"
        assert row["to_id"] == "zeta"
    finally:
        window.reset()
        conn.close()


def test_window_cap_respected(brain_db) -> None:
    conn = connect(brain_db)
    window = get_learning_window()
    window.reset()
    try:
        cfg = BrainConfig(learning={"session_window_size": 5})
        for index in range(8):
            node_id = f"n{index}"
            insert_node(conn, node_id=node_id, title=node_id)
            window.record_neuron_hits("s3", [node_id])
            process_post_tool(conn, "s3", "Edit", {}, config=cfg)
        conn.commit()
        assert len(window.windows["s3"]) <= 5
    finally:
        window.reset()
        conn.close()
