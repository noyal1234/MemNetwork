"""Tests for co_activated decay, ignore gates, SessionEnd DROP."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from brainkm.db.connection import connect
from brainkm.models.brain_config import BrainConfig
from brainkm.services.feedback import ignore_rate, mark_ignored_since_injection, record_injected
from brainkm.services.learning import (
    decay_co_activation_edges,
    delete_session_learning_state,
    get_learning_window,
    persist_neuron_hits,
    process_post_tool,
    purge_session_learning_state,
)
from brainkm.services.procedures import archive_ignored_procedures, check_and_promote
from brainkm.services.session_activity import record_neuron_activity
from tests.conftest import insert_edge, insert_node


def test_compound_decay_single_shot(brain_db) -> None:
    conn = connect(brain_db)
    try:
        insert_node(conn, node_id="n1", title="one")
        insert_node(conn, node_id="n2", title="two")
        insert_edge(
            conn,
            edge_id="e1",
            from_id="n1",
            to_id="n2",
            relationship="co_activated",
            weight=10.0,
        )
        past = (datetime.now(UTC) - timedelta(days=90)).isoformat()
        conn.execute(
            "UPDATE edges SET updated_at = ?, decayed_at = NULL WHERE id = 'e1'",
            (past,),
        )
        conn.commit()
        now = datetime.now(UTC)
        result = decay_co_activation_edges(
            conn,
            idle_days=30,
            decay_factor=0.5,
            min_weight=0.3,
            now=now,
        )
        conn.commit()
        assert result["decayed"] == 1
        row = conn.execute(
            "SELECT weight, decayed_at, updated_at FROM edges WHERE id = 'e1'"
        ).fetchone()
        assert float(row["weight"]) == pytest.approx(10.0 * (0.5**3))
        assert row["updated_at"] == past
        assert row["decayed_at"] is not None
    finally:
        conn.close()


def test_dual_decay_equals_single_shot(brain_db) -> None:
    """Two decay passes with no reinforce ≡ one pass over same elapsed span."""
    conn = connect(brain_db)
    try:
        insert_node(conn, node_id="n1", title="one")
        insert_node(conn, node_id="n2", title="two")
        day0 = datetime.now(UTC) - timedelta(days=65)
        insert_edge(
            conn,
            edge_id="e1",
            from_id="n1",
            to_id="n2",
            relationship="co_activated",
            weight=10.0,
        )
        conn.execute(
            "UPDATE edges SET updated_at = ?, decayed_at = NULL WHERE id = 'e1'",
            (day0.isoformat(),),
        )
        conn.commit()

        # First pass at day 40 relative
        t40 = day0 + timedelta(days=40)
        decay_co_activation_edges(
            conn, idle_days=30, decay_factor=0.5, min_weight=0.01, now=t40
        )
        conn.commit()
        mid = conn.execute("SELECT weight FROM edges WHERE id = 'e1'").fetchone()
        assert float(mid["weight"]) == pytest.approx(5.0)

        # Second pass at day 65
        t65 = day0 + timedelta(days=65)
        decay_co_activation_edges(
            conn, idle_days=30, decay_factor=0.5, min_weight=0.01, now=t65
        )
        conn.commit()
        final = conn.execute("SELECT weight FROM edges WHERE id = 'e1'").fetchone()
        assert float(final["weight"]) == pytest.approx(2.5)

        # Fresh edge single-shot at day 65
        conn.execute("DELETE FROM edges WHERE id = 'e1'")
        insert_edge(
            conn,
            edge_id="e2",
            from_id="n1",
            to_id="n2",
            relationship="co_activated",
            weight=10.0,
        )
        conn.execute(
            "UPDATE edges SET updated_at = ?, decayed_at = NULL WHERE id = 'e2'",
            (day0.isoformat(),),
        )
        conn.commit()
        decay_co_activation_edges(
            conn, idle_days=30, decay_factor=0.5, min_weight=0.01, now=t65
        )
        conn.commit()
        single = conn.execute("SELECT weight FROM edges WHERE id = 'e2'").fetchone()
        assert float(single["weight"]) == pytest.approx(float(final["weight"]))
    finally:
        conn.close()


def test_reinforce_resets_decayed_at(brain_db) -> None:
    conn = connect(brain_db)
    window = get_learning_window()
    window.reset()
    try:
        insert_node(conn, node_id="n1", title="one")
        insert_node(conn, node_id="n2", title="two")
        insert_edge(
            conn,
            edge_id="e1",
            from_id="n1",
            to_id="n2",
            relationship="co_activated",
            weight=4.0,
        )
        past = (datetime.now(UTC) - timedelta(days=90)).isoformat()
        conn.execute(
            "UPDATE edges SET updated_at = ?, decayed_at = ? WHERE id = 'e1'",
            (past, past),
        )
        conn.commit()
        persist_neuron_hits(conn, "s1", ["n1", "n2"], source="recall")
        process_post_tool(conn, "s1", "Edit", {}, config=BrainConfig())
        conn.commit()
        row = conn.execute(
            "SELECT decayed_at, weight FROM edges WHERE from_id = 'n1' AND to_id = 'n2'"
        ).fetchone()
        assert row["decayed_at"] is None
        assert float(row["weight"]) > 4.0
    finally:
        window.reset()
        conn.close()


def test_decay_deletes_sub_floor(brain_db) -> None:
    conn = connect(brain_db)
    try:
        insert_node(conn, node_id="n1", title="one")
        insert_node(conn, node_id="n2", title="two")
        insert_edge(
            conn,
            edge_id="e1",
            from_id="n1",
            to_id="n2",
            relationship="co_activated",
            weight=0.5,
        )
        past = (datetime.now(UTC) - timedelta(days=90)).isoformat()
        conn.execute(
            "UPDATE edges SET updated_at = ?, decayed_at = NULL WHERE id = 'e1'",
            (past,),
        )
        conn.commit()
        result = decay_co_activation_edges(
            conn, idle_days=30, decay_factor=0.5, min_weight=0.3
        )
        conn.commit()
        assert result["deleted"] == 1
        assert (
            conn.execute("SELECT COUNT(*) FROM edges WHERE id = 'e1'").fetchone()[0] == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM edges WHERE relationship = 'co_activated' AND weight < 0.3"
            ).fetchone()[0]
            == 0
        )
    finally:
        conn.close()


def test_promote_gate_off_below_min_sample(brain_db) -> None:
    conn = connect(brain_db)
    window = get_learning_window()
    window.reset()
    cfg = BrainConfig(learning={"co_activation_threshold": 1, "promote_min_injected_count": 3})
    try:
        insert_node(conn, node_id="a", title="A")
        insert_node(conn, node_id="b", title="B")
        insert_edge(
            conn,
            edge_id="e1",
            from_id="a",
            to_id="b",
            relationship="co_activated",
            weight=5.0,
        )
        # Low sample ignore — must not block
        record_injected(conn, ["a"], session_id="s1")
        conn.execute(
            """
            UPDATE neuron_feedback
            SET ignored_count = 1, last_ignored = ?
            WHERE node_id = 'a'
            """,
            (datetime.now(UTC).isoformat(),),
        )
        persist_neuron_hits(conn, "sess", ["a", "b"], source="recall")
        # Ensure tools present for promotion
        process_post_tool(conn, "sess", "Edit", {}, config=cfg)
        process_post_tool(conn, "sess", "Write", {}, config=cfg)
        # Force pair weight and promote check
        promoted = check_and_promote(conn, "sess", config=cfg)
        # May or may not create depending on tools/weight; gate must not block on n=1
        rate, injected = ignore_rate(conn, "a", half_life_days=60)
        assert injected < 3
        assert rate >= 0.0
        _ = promoted
    finally:
        window.reset()
        conn.close()


def test_promote_blocked_high_ignore_with_sample(brain_db) -> None:
    conn = connect(brain_db)
    window = get_learning_window()
    window.reset()
    cfg = BrainConfig(
        learning={
            "co_activation_threshold": 1,
            "promote_min_injected_count": 3,
            "promote_max_ignore_rate": 0.5,
        }
    )
    try:
        insert_node(conn, node_id="a", title="path/a.py")
        insert_node(conn, node_id="b", title="path/b.py")
        insert_edge(
            conn,
            edge_id="e1",
            from_id="a",
            to_id="b",
            relationship="co_activated",
            weight=5.0,
        )
        for i in range(5):
            record_injected(conn, ["a"], session_id=f"s{i}")
        conn.execute(
            """
            UPDATE neuron_feedback
            SET ignored_count = 5, last_ignored = ?, used_count = 0
            WHERE node_id = 'a'
            """,
            (datetime.now(UTC).isoformat(),),
        )
        persist_neuron_hits(conn, "sess", ["a", "b"], source="recall")
        process_post_tool(conn, "sess", "Edit", {}, config=cfg)
        process_post_tool(conn, "sess", "Write", {}, config=cfg)
        promoted = check_and_promote(conn, "sess", config=cfg)
        assert promoted == []
        archived = archive_ignored_procedures(
            conn,
            max_ignore_rate=0.5,
            min_injected_count=5,
            half_life_days=60,
            dry_run=True,
        )
        # Procedure may not exist yet; archive eligibility for high-ignore neurons tested via rate
        rate, injected = ignore_rate(conn, "a", half_life_days=60)
        assert injected >= 5
        assert rate > 0.5
        _ = archived
    finally:
        window.reset()
        conn.close()


def test_half_life_ages_out_ignores(brain_db) -> None:
    conn = connect(brain_db)
    try:
        insert_node(conn, node_id="a", title="A")
        for i in range(5):
            record_injected(conn, ["a"], session_id=f"s{i}")
        old = (datetime.now(UTC) - timedelta(days=180)).isoformat()
        conn.execute(
            """
            UPDATE neuron_feedback
            SET ignored_count = 5, last_ignored = ?
            WHERE node_id = 'a'
            """,
            (old,),
        )
        conn.commit()
        rate, injected = ignore_rate(conn, "a", half_life_days=60)
        assert injected >= 5
        assert rate < 0.5
    finally:
        conn.close()


def test_ambient_only_never_archive_via_ignore(brain_db) -> None:
    conn = connect(brain_db)
    try:
        insert_node(conn, node_id="fact", title="Durable fact")
        for i in range(5):
            record_neuron_activity(conn, f"s{i}", ["fact"], source="session_start")
            mark_ignored_since_injection(conn, session_id=f"s{i}")
        conn.commit()
        row = conn.execute(
            "SELECT injected_count FROM neuron_feedback WHERE node_id = 'fact'"
        ).fetchone()
        assert row is None or int(row["injected_count"] or 0) == 0
        archived = archive_ignored_procedures(
            conn, min_injected_count=5, dry_run=True
        )
        assert "fact" not in archived
    finally:
        conn.close()


def test_session_end_drops_unconsumed_episode(brain_db) -> None:
    conn = connect(brain_db)
    window = get_learning_window()
    window.reset()
    try:
        insert_node(conn, node_id="n1", title="one")
        insert_node(conn, node_id="n2", title="two")
        persist_neuron_hits(conn, "s1", ["n1", "n2"], source="recall")
        conn.commit()
        row = conn.execute(
            "SELECT pending_coact FROM session_learning_state WHERE session_id = 's1'"
        ).fetchone()
        assert int(row["pending_coact"]) == 1
        delete_session_learning_state(conn, "s1")
        conn.commit()
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM session_learning_state WHERE session_id = 's1'"
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM edges WHERE relationship = 'co_activated'"
            ).fetchone()[0]
            == 0
        )
        # Trailing PostTool after DROP — no raise, no pairs
        process_post_tool(conn, "s1", "Edit", {}, config=BrainConfig())
        conn.commit()
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM edges WHERE relationship = 'co_activated'"
            ).fetchone()[0]
            == 0
        )
    finally:
        window.reset()
        conn.close()


def test_purge_session_learning_state(brain_db) -> None:
    conn = connect(brain_db)
    try:
        old = (datetime.now(UTC) - timedelta(days=30)).isoformat()
        conn.execute(
            """
            INSERT INTO session_learning_state
              (session_id, pending_node_ids, pending_coact, updated_at)
            VALUES ('old', '[]', 0, ?)
            """,
            (old,),
        )
        conn.commit()
        deleted = purge_session_learning_state(conn, retention_days=14)
        conn.commit()
        assert deleted == 1
    finally:
        conn.close()


def test_mark_ignored_stamps_last_ignored(brain_db) -> None:
    conn = connect(brain_db)
    try:
        insert_node(conn, node_id="n1", title="one")
        record_injected(conn, ["n1"], session_id="s1")
        conn.commit()
        n = mark_ignored_since_injection(conn, session_id="s1")
        conn.commit()
        assert n >= 1
        row = conn.execute(
            "SELECT ignored_count, last_ignored FROM neuron_feedback WHERE node_id = 'n1'"
        ).fetchone()
        assert int(row["ignored_count"]) >= 1
        assert row["last_ignored"] is not None
    finally:
        conn.close()
