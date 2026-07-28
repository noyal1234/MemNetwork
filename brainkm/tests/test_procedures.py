"""Tests for V2 procedure promotion helpers."""

from __future__ import annotations

from brainkm.db.connection import connect
from brainkm.models.brain_config import BrainConfig
from brainkm.services.learning import get_learning_window, persist_neuron_hits, process_post_tool
from brainkm.services.procedures import (
    check_and_promote,
    find_promotable_pairs,
    ordered_external_tools,
    upsert_procedure_neuron,
)
from tests.conftest import insert_edge, insert_node


def test_ordered_external_tools_preserves_first_seen() -> None:
    assert ordered_external_tools(["Edit", "recall", "Shell", "Edit", "Write"]) == [
        "Edit",
        "Shell",
        "Write",
    ]


def test_find_promotable_pairs_threshold(brain_db) -> None:
    conn = connect(brain_db)
    try:
        insert_node(conn, node_id="a", title="A")
        insert_node(conn, node_id="b", title="B")
        insert_edge(
            conn, edge_id="e1", from_id="a", to_id="b", relationship="co_activated", weight=3
        )
        conn.commit()
        assert find_promotable_pairs(conn, threshold=3) == [("a", "b")]
        assert find_promotable_pairs(conn, threshold=4) == []
    finally:
        conn.close()


def test_find_promotable_pairs_scopes_to_session_hits(brain_db) -> None:
    conn = connect(brain_db)
    try:
        insert_node(conn, node_id="a", title="A")
        insert_node(conn, node_id="b", title="B")
        insert_node(conn, node_id="c", title="C")
        insert_node(conn, node_id="d", title="D")
        insert_edge(
            conn, edge_id="e1", from_id="a", to_id="b", relationship="co_activated", weight=3
        )
        insert_edge(
            conn, edge_id="e2", from_id="c", to_id="d", relationship="co_activated", weight=5
        )
        conn.commit()
        assert find_promotable_pairs(
            conn,
            threshold=3,
            session_neuron_ids={"a", "b"},
        ) == [("a", "b")]
        assert find_promotable_pairs(conn, threshold=3, session_neuron_ids=set()) == []
    finally:
        conn.close()


def test_upsert_procedure_stores_tool_chain_body(brain_db) -> None:
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
        row = conn.execute(
            "SELECT title, content FROM nodes WHERE id = ?",
            (first,),
        ).fetchone()
        assert row["title"] == "Edit → Shell"
        assert "Tools: Edit → Shell" in row["content"]
        assert "1. Edit" in row["content"]
        assert "2. Shell" in row["content"]
        # Path/symbol-ish related context only (evergreen rule titles omitted).
        assert "- Auth" in row["content"]
        assert "- Middleware" in row["content"]
        count = conn.execute(
            "SELECT COUNT(*) AS total FROM nodes WHERE kind = 'procedure'"
        ).fetchone()
        assert count["total"] == 1

        # Same tools + different neuron pair merges (bumps use, no new row).
        insert_node(conn, node_id="c", title="Other")
        insert_node(conn, node_id="d", title="Thing")
        conn.commit()
        third = upsert_procedure_neuron(
            conn,
            neuron_ids=["c", "d"],
            tool_names=["Edit", "Shell"],
            session_id="sess2",
        )
        conn.commit()
        assert third is None
        count2 = conn.execute(
            "SELECT COUNT(*) AS total FROM nodes WHERE kind = 'procedure' AND valid_until IS NULL"
        ).fetchone()
        assert count2["total"] == 1
        use = conn.execute(
            "SELECT use_count FROM nodes WHERE id = ?", (first,)
        ).fetchone()
        assert int(use["use_count"] or 0) >= 1
    finally:
        conn.close()


def test_upsert_skips_evergreen_related_context(brain_db) -> None:
    conn = connect(brain_db)
    try:
        insert_node(conn, node_id="a", title="Redaction chokepoint")
        insert_node(conn, node_id="b", title="Token budget policy")
        conn.commit()
        created = upsert_procedure_neuron(
            conn,
            neuron_ids=["a", "b"],
            tool_names=["Write", "Shell"],
            session_id="sess",
        )
        conn.commit()
        assert created is not None
        row = conn.execute(
            "SELECT content FROM nodes WHERE id = ?", (created,)
        ).fetchone()
        assert "Related context" not in row["content"]
        assert "Redaction chokepoint" not in row["content"]
    finally:
        conn.close()


def test_dedupe_tool_chain_procedures_keeps_highest_use(brain_db) -> None:
    from brainkm.services.procedures import dedupe_tool_chain_procedures

    conn = connect(brain_db)
    try:
        insert_node(
            conn,
            node_id="p1",
            kind="procedure",
            subtype="tool_chain",
            title="Write → Shell",
            content="Tools: Write → Shell",
        )
        insert_node(
            conn,
            node_id="p2",
            kind="procedure",
            subtype="tool_chain",
            title="Write → Shell",
            content="Tools: Write → Shell\nextra",
        )
        conn.execute("UPDATE nodes SET use_count = 5 WHERE id = 'p1'")
        conn.execute("UPDATE nodes SET use_count = 1 WHERE id = 'p2'")
        conn.commit()
        archived = dedupe_tool_chain_procedures(conn, dry_run=False)
        conn.commit()
        assert archived == ["p2"]
        active = conn.execute(
            "SELECT id FROM nodes WHERE kind='procedure' AND valid_until IS NULL"
        ).fetchall()
        assert [r["id"] for r in active] == ["p1"]
    finally:
        conn.close()


def test_check_and_promote_creates_procedure(brain_db) -> None:
    conn = connect(brain_db)
    window = get_learning_window()
    window.reset()
    try:
        insert_node(conn, node_id="a", title="Auth")
        insert_node(conn, node_id="b", title="Token")
        insert_edge(
            conn, edge_id="e1", from_id="a", to_id="b", relationship="co_activated", weight=3
        )
        persist_neuron_hits(conn, "sess", ["a", "b"], source="test")
        conn.execute(
            """
            INSERT INTO session_activity (
              id, session_id, kind, node_id, tool_name, source, created_at
            ) VALUES
              ('t1', 'sess', 'tool_use', NULL, 'Edit', 'test', datetime('now')),
              ('t2', 'sess', 'tool_use', NULL, 'Shell', 'test', datetime('now'))
            """
        )
        conn.commit()
        promoted = check_and_promote(conn, "sess", config=BrainConfig())
        conn.commit()
        assert len(promoted) == 1
        body = conn.execute(
            "SELECT content FROM nodes WHERE id = ?",
            (promoted[0],),
        ).fetchone()["content"]
        assert "Tools: Edit → Shell" in body
    finally:
        window.reset()
        conn.close()


def test_check_and_promote_ignores_unrelated_global_pairs(brain_db) -> None:
    conn = connect(brain_db)
    window = get_learning_window()
    window.reset()
    try:
        insert_node(conn, node_id="a", title="Auth")
        insert_node(conn, node_id="b", title="Token")
        insert_node(conn, node_id="c", title="Unrelated")
        insert_node(conn, node_id="d", title="Other")
        insert_edge(
            conn, edge_id="e1", from_id="a", to_id="b", relationship="co_activated", weight=3
        )
        insert_edge(
            conn, edge_id="e2", from_id="c", to_id="d", relationship="co_activated", weight=9
        )
        persist_neuron_hits(conn, "sess", ["a", "b"], source="test")
        conn.execute(
            """
            INSERT INTO session_activity (
              id, session_id, kind, node_id, tool_name, source, created_at
            ) VALUES
              ('t1', 'sess', 'tool_use', NULL, 'Edit', 'test', datetime('now')),
              ('t2', 'sess', 'tool_use', NULL, 'Write', 'test', datetime('now'))
            """
        )
        conn.commit()
        promoted = check_and_promote(conn, "sess", config=BrainConfig())
        conn.commit()
        assert len(promoted) == 1
        spawned = conn.execute(
            """
            SELECT to_id FROM edges
            WHERE from_id = ? AND relationship = 'spawned'
            ORDER BY to_id
            """,
            (promoted[0],),
        ).fetchall()
        assert [row["to_id"] for row in spawned] == ["a", "b"]
    finally:
        window.reset()
        conn.close()


def test_process_post_tool_e2e_promotes_procedure(brain_db) -> None:
    """Full loop: three hit episodes → procedure with tool chain body."""
    conn = connect(brain_db)
    window = get_learning_window()
    window.reset()
    cfg = BrainConfig(learning={"co_activation_threshold": 3})
    try:
        insert_node(conn, node_id="n1", title="Decision A")
        insert_node(conn, node_id="n2", title="Decision B")
        # Unrelated global pair that must not promote.
        insert_node(conn, node_id="x1", title="Noise X")
        insert_node(conn, node_id="x2", title="Noise Y")
        insert_edge(
            conn,
            edge_id="noise",
            from_id="x1",
            to_id="x2",
            relationship="co_activated",
            weight=10,
        )
        for tool in ("Edit", "Write", "Edit"):
            persist_neuron_hits(conn, "sess-e2e", ["n1", "n2"], source="recall")
            process_post_tool(conn, "sess-e2e", tool, {}, config=cfg)
        conn.commit()

        procs = conn.execute(
            "SELECT id, title, content FROM nodes WHERE kind = 'procedure' AND valid_until IS NULL"
        ).fetchall()
        assert len(procs) == 1
        assert "Edit → Write" in procs[0]["title"]
        assert "1. Edit" in procs[0]["content"]
        assert "2. Write" in procs[0]["content"]
        spawned = {
            row["to_id"]
            for row in conn.execute(
                "SELECT to_id FROM edges WHERE from_id = ? AND relationship = 'spawned'",
                (procs[0]["id"],),
            ).fetchall()
        }
        assert spawned == {"n1", "n2"}
    finally:
        window.reset()
        conn.close()
