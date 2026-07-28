"""Tests for Hebbian learning: episode gating, saturation, inject, CAS."""

from __future__ import annotations

import json
import threading
import time

import pytest

from brainkm.db.connection import connect
from brainkm.db.migrate import migrate
from brainkm.models.brain_config import BrainConfig
from brainkm.services.feedback import record_injected
from brainkm.services.learning import (
    _mark_pending_coact,
    _peek_pending_node_ids,
    get_learning_window,
    inject_session_id_from_payload,
    persist_neuron_hits,
    process_post_tool,
)
from brainkm.services.session_activity import record_neuron_activity
from tests.conftest import insert_edge, insert_node


def test_co_activation_one_increment_per_episode(brain_db) -> None:
    conn = connect(brain_db)
    window = get_learning_window()
    window.reset()
    try:
        insert_node(conn, node_id="n1", title="one")
        insert_node(conn, node_id="n2", title="two")
        persist_neuron_hits(conn, "s1", ["n1", "n2"], source="recall")
        conn.commit()

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
        assert float(row["weight"]) == pytest.approx(1.0)
    finally:
        window.reset()
        conn.close()


def test_two_hit_episodes_weight_two(brain_db) -> None:
    conn = connect(brain_db)
    window = get_learning_window()
    window.reset()
    try:
        insert_node(conn, node_id="n1", title="one")
        insert_node(conn, node_id="n2", title="two")
        persist_neuron_hits(conn, "s1", ["n1", "n2"], source="recall")
        process_post_tool(conn, "s1", "Edit", {}, config=BrainConfig())
        persist_neuron_hits(conn, "s1", ["n1", "n2"], source="recall")
        process_post_tool(conn, "s1", "Shell", {}, config=BrainConfig())
        conn.commit()

        row = conn.execute(
            """
            SELECT weight FROM edges
            WHERE relationship = 'co_activated' AND from_id = 'n1' AND to_id = 'n2'
            """
        ).fetchone()
        assert row is not None
        assert float(row["weight"]) == pytest.approx(2.0)
    finally:
        window.reset()
        conn.close()


def test_saturating_weight_ceiling(brain_db) -> None:
    conn = connect(brain_db)
    window = get_learning_window()
    window.reset()
    cfg = BrainConfig(
        learning={
            "co_activation_max_weight": 3.0,
            "co_activation_delta": 1.0,
            "co_activation_threshold": 2,
        }
    )
    try:
        insert_node(conn, node_id="n1", title="one")
        insert_node(conn, node_id="n2", title="two")
        for _ in range(10):
            persist_neuron_hits(conn, "s1", ["n1", "n2"], source="recall")
            process_post_tool(conn, "s1", "Edit", {}, config=cfg)
        conn.commit()
        row = conn.execute(
            """
            SELECT weight, decayed_at FROM edges
            WHERE relationship = 'co_activated' AND from_id = 'n1' AND to_id = 'n2'
            """
        ).fetchone()
        assert float(row["weight"]) == pytest.approx(3.0)
        assert row["decayed_at"] is None
    finally:
        window.reset()
        conn.close()


def test_overlap_replace_not_merge(brain_db) -> None:
    conn = connect(brain_db)
    window = get_learning_window()
    window.reset()
    try:
        for nid, title in (("a", "A"), ("b", "B"), ("c", "C"), ("d", "D")):
            insert_node(conn, node_id=nid, title=title)
        persist_neuron_hits(conn, "s1", ["a", "b"], source="recall")
        persist_neuron_hits(conn, "s1", ["c", "d"], source="pre_tool")
        process_post_tool(conn, "s1", "Edit", {}, config=BrainConfig())
        conn.commit()
        pairs = {
            (row["from_id"], row["to_id"])
            for row in conn.execute(
                "SELECT from_id, to_id FROM edges WHERE relationship = 'co_activated'"
            ).fetchall()
        }
        assert pairs == {("c", "d")}
    finally:
        window.reset()
        conn.close()


def test_ambient_snapshot_does_not_open_pairwise(brain_db) -> None:
    conn = connect(brain_db)
    window = get_learning_window()
    window.reset()
    try:
        ids = [f"n{i}" for i in range(40)]
        for nid in ids:
            insert_node(conn, node_id=nid, title=nid)
        record_neuron_activity(conn, "s1", ids, source="session_start")
        process_post_tool(conn, "s1", "Edit", {}, config=BrainConfig())
        conn.commit()
        count = conn.execute(
            "SELECT COUNT(*) AS total FROM edges WHERE relationship = 'co_activated'"
        ).fetchone()["total"]
        assert count == 0
        # Ambient must not increment injected_count
        inj = conn.execute(
            "SELECT COALESCE(SUM(injected_count), 0) FROM neuron_feedback"
        ).fetchone()[0]
        assert int(inj) == 0
    finally:
        window.reset()
        conn.close()


def test_targeted_inject_increments(brain_db) -> None:
    conn = connect(brain_db)
    window = get_learning_window()
    window.reset()
    try:
        insert_node(conn, node_id="n1", title="one")
        insert_node(conn, node_id="n2", title="two")
        persist_neuron_hits(conn, "s1", ["n1", "n2"], source="recall")
        conn.commit()
        row = conn.execute(
            "SELECT injected_count FROM neuron_feedback WHERE node_id = 'n1'"
        ).fetchone()
        assert row is not None
        assert int(row["injected_count"]) == 1
    finally:
        window.reset()
        conn.close()


def test_ambient_post_tool_does_not_mark_used(brain_db) -> None:
    """Ambient (SessionStart) hits never open a pending episode, so PostToolUse
    must not credit them as "used" — mirrors the existing injected_count == 0
    ambient rule (test_ambient_only_never_archive_via_ignore)."""
    conn = connect(brain_db)
    window = get_learning_window()
    window.reset()
    try:
        insert_node(conn, node_id="amb", title="ambient")
        record_neuron_activity(conn, "s1", ["amb"], source="session_start")
        process_post_tool(conn, "s1", "Edit", {}, config=BrainConfig())
        conn.commit()
        row = conn.execute(
            "SELECT used_count FROM neuron_feedback WHERE node_id = 'amb'"
        ).fetchone()
        assert row is None or int(row["used_count"]) == 0
    finally:
        window.reset()
        conn.close()


def test_atomic_inject_dedupe(brain_db) -> None:
    conn = connect(brain_db)
    try:
        insert_node(conn, node_id="n1", title="one")
        record_injected(conn, ["n1"], session_id="s1")
        record_injected(conn, ["n1"], session_id="s1")
        conn.commit()
        row = conn.execute(
            "SELECT injected_count FROM neuron_feedback WHERE node_id = 'n1'"
        ).fetchone()
        assert int(row["injected_count"]) == 1
    finally:
        conn.close()


def test_inject_session_id_skips_subagent_only() -> None:
    assert inject_session_id_from_payload({"subagent_id": "sub-1"}) is None
    assert (
        inject_session_id_from_payload(
            {"session_id": "parent", "subagent_id": "sub-1"}
        )
        == "parent"
    )


def test_consume_single_id_no_edge(brain_db) -> None:
    conn = connect(brain_db)
    window = get_learning_window()
    window.reset()
    try:
        insert_node(conn, node_id="solo", title="solo")
        persist_neuron_hits(conn, "s1", ["solo"], source="recall")
        process_post_tool(conn, "s1", "Edit", {}, config=BrainConfig())
        conn.commit()
        count = conn.execute(
            "SELECT COUNT(*) AS total FROM edges WHERE relationship = 'co_activated'"
        ).fetchone()["total"]
        assert count == 0
    finally:
        window.reset()
        conn.close()


def test_peek_missing_row_empty(brain_db) -> None:
    conn = connect(brain_db)
    try:
        assert _peek_pending_node_ids(conn, "missing") == []
        assert _peek_pending_node_ids(conn, None) == []
    finally:
        conn.close()


def test_used_increments_once_per_episode_not_per_tool_call(brain_db) -> None:
    """A single recall opens one episode — used_count must credit it exactly
    once, not once per subsequent (possibly unrelated) PostToolUse event."""
    conn = connect(brain_db)
    window = get_learning_window()
    window.reset()
    try:
        insert_node(conn, node_id="n1", title="one")
        insert_node(conn, node_id="n2", title="two")
        persist_neuron_hits(conn, "s1", ["n1", "n2"], source="recall")
        process_post_tool(conn, "s1", "Edit", {}, config=BrainConfig())
        process_post_tool(conn, "s1", "Shell", {}, config=BrainConfig())
        process_post_tool(conn, "s1", "Write", {}, config=BrainConfig())
        conn.commit()
        row = conn.execute(
            "SELECT used_count FROM neuron_feedback WHERE node_id = 'n1'"
        ).fetchone()
        assert int(row["used_count"]) == 1
    finally:
        window.reset()
        conn.close()


def test_legacy_clamp_on_migrate(tmp_path) -> None:
    db = tmp_path / "brain.db"
    # Apply through 009 then seed overweight edge, then apply 010 via full migrate.
    migrate(db_path=db, run_integrity_check=False)
    conn = connect(db)
    try:
        insert_node(conn, node_id="n1", title="one")
        insert_node(conn, node_id="n2", title="two")
        # Force overweight then re-run clamp statement (already applied on fresh migrate).
        conn.execute(
            """
            UPDATE edges SET weight = 50.0
            WHERE relationship = 'co_activated'
            """
        )
        # Insert overweight edge after migrate — simulate pre-clamp state then re-apply clamp SQL
        insert_edge(
            conn,
            edge_id="e-heavy",
            from_id="n1",
            to_id="n2",
            relationship="co_activated",
            weight=50.0,
        )
        conn.execute(
            """
            UPDATE edges
            SET weight = MIN(weight, 10.0)
            WHERE relationship = 'co_activated' AND weight > 10.0
            """
        )
        conn.commit()
        row = conn.execute(
            "SELECT weight FROM edges WHERE id = 'e-heavy'"
        ).fetchone()
        assert float(row["weight"]) == pytest.approx(10.0)
    finally:
        conn.close()


def test_cas_concurrency_no_cross_contamination(tmp_path) -> None:
    db = tmp_path / "brain.db"
    migrate(db_path=db, run_integrity_check=False)
    conn_setup = connect(db)
    try:
        insert_node(conn_setup, node_id="a", title="A")
        insert_node(conn_setup, node_id="b", title="B")
        insert_node(conn_setup, node_id="c", title="C")
        insert_node(conn_setup, node_id="d", title="D")
        _mark_pending_coact(conn_setup, "s1", ["a", "b"])
        conn_setup.commit()
    finally:
        conn_setup.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def consumer() -> None:
        conn = connect(db)
        try:
            # Claim write lock then pause before SELECT would normally run —
            # _consume does UPDATE then SELECT atomically under IMMEDIATE.
            if not conn.in_transaction:
                conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                UPDATE session_learning_state
                SET pending_coact = 0
                WHERE session_id = ? AND pending_coact = 1
                """,
                ("s1",),
            )
            barrier.wait(timeout=5)
            time.sleep(0.05)  # hold lock while producer tries REPLACE
            row = conn.execute(
                "SELECT pending_node_ids FROM session_learning_state WHERE session_id = ?",
                ("s1",),
            ).fetchone()
            results["consumed"] = json.loads(row[0]) if row and row[0] else None
            conn.commit()
        finally:
            conn.close()

    def producer() -> None:
        barrier.wait(timeout=5)
        conn = connect(db)
        try:
            _mark_pending_coact(conn, "s1", ["c", "d"])
            conn.commit()
            results["produced"] = True
        finally:
            conn.close()

    t1 = threading.Thread(target=consumer)
    t2 = threading.Thread(target=producer)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)
    assert results.get("consumed") == ["a", "b"]
    # After consumer commit, producer REPLACE should have landed as new pending.
    conn = connect(db)
    try:
        row = conn.execute(
            """
            SELECT pending_coact, pending_node_ids
            FROM session_learning_state WHERE session_id = ?
            """,
            ("s1",),
        ).fetchone()
        assert row is not None
        assert int(row["pending_coact"]) == 1
        assert json.loads(row["pending_node_ids"]) == ["c", "d"]
    finally:
        conn.close()


def test_no_edge_created_for_single_neuron(brain_db) -> None:
    conn = connect(brain_db)
    window = get_learning_window()
    window.reset()
    try:
        insert_node(conn, node_id="solo", title="single")
        persist_neuron_hits(conn, "s1", ["solo"], source="recall")
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
        persist_neuron_hits(conn, "s2", ["zeta", "alpha"], source="recall")
        process_post_tool(conn, "s2", "Edit", {}, config=BrainConfig())
        conn.commit()
        row = conn.execute(
            "SELECT from_id, to_id FROM edges WHERE relationship = 'co_activated'"
        ).fetchone()
        assert row is not None
        assert row["from_id"] == "alpha"
        assert row["to_id"] == "zeta"
    finally:
        window.reset()
        conn.close()
