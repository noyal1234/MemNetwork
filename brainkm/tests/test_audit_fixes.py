"""Tests for audit fixes: cross-process learning, recall, session_status, new tools."""

from __future__ import annotations

import pytest

from brainkm.db.connection import connect
from brainkm.models.brain_config import BrainConfig, RecallConfig
from brainkm.models.schemas import (
    BrainStatsRequest,
    ContextPackRequest,
    GraphSyncRequest,
    RecallRequest,
    SessionStatusRequest,
)
from brainkm.services.abstention import should_abstain
from brainkm.services.learning import (
    get_learning_window,
    persist_neuron_hits,
    process_post_tool,
)
from brainkm.services.memory import token_count
from brainkm.services.recall_dedup import search_session_chunks
from brainkm.services.session_activity import flush_use_counts, get_session_activity
from brainkm.tools.dispatch import (
    BrainRuntime,
    handle_brain_stats,
    handle_context_pack,
    handle_graph_sync,
    handle_recall,
    handle_session_status,
)
from tests.conftest import insert_node


@pytest.fixture
def runtime(tmp_path) -> BrainRuntime:
    from brainkm.db.migrate import migrate

    migrate(db_path=tmp_path / ".brain" / "brain.db", run_integrity_check=True)
    return BrainRuntime(project_dir=tmp_path)


def test_cross_process_session_activity_flush(brain_db) -> None:
    """Simulate hook subprocesses: write hits in one process state, flush with cleared memory."""
    conn = connect(brain_db)
    window = get_learning_window()
    window.reset()
    get_session_activity().recalled_nodes.clear()
    try:
        insert_node(conn, node_id="hit1", title="decision A", content="use SQLite")
        conn.commit()

        # Subprocess 1: SessionStart / PreTool records hits to SQLite
        persist_neuron_hits(conn, "sess-x", ["hit1"], source="session_start")
        conn.commit()

        # Subprocess 2: clear in-memory state (fresh CLI process)
        window.reset()
        get_session_activity().recalled_nodes.clear()

        flushed = flush_use_counts(conn, "sess-x")
        conn.commit()
        assert flushed == 1
        use_count = conn.execute(
            "SELECT use_count FROM nodes WHERE id = 'hit1'"
        ).fetchone()[0]
        assert use_count == 1
    finally:
        window.reset()
        conn.close()


def test_cross_process_co_activation(brain_db) -> None:
    conn = connect(brain_db)
    window = get_learning_window()
    window.reset()
    try:
        insert_node(conn, node_id="a1", title="alpha")
        insert_node(conn, node_id="b1", title="beta")
        conn.commit()

        persist_neuron_hits(conn, "sess-y", ["a1", "b1"], source="pre_tool")
        conn.commit()

        # Fresh process: empty in-memory window
        window.reset()
        process_post_tool(conn, "sess-y", "Edit", {}, config=BrainConfig())
        process_post_tool(conn, "sess-y", "Shell", {}, config=BrainConfig())
        conn.commit()

        row = conn.execute(
            """
            SELECT weight FROM edges
            WHERE relationship = 'co_activated'
              AND from_id = 'a1' AND to_id = 'b1'
            """
        ).fetchone()
        assert row is not None
        assert int(row["weight"]) >= 1
    finally:
        window.reset()
        conn.close()


def test_search_session_chunks_sanitizes_special_chars(brain_db) -> None:
    conn = connect(brain_db)
    try:
        # Should not raise even with FTS special characters.
        hits = search_session_chunks(conn, 'auth "login (broken)', limit=5)
        assert hits == []
    finally:
        conn.close()


def test_session_status_archives_previous(runtime, tmp_path) -> None:
    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        first = handle_session_status(
            conn,
            SessionStatusRequest(session_id="s1", title="v1", body="first context"),
        )
        second = handle_session_status(
            conn,
            SessionStatusRequest(session_id="s1", title="v2", body="second context"),
        )
        assert first.node_id != second.node_id
        archived = conn.execute(
            "SELECT valid_until FROM nodes WHERE id = ?",
            (first.node_id,),
        ).fetchone()
        assert archived["valid_until"] is not None
        active = conn.execute(
            """
            SELECT COUNT(*) AS n FROM nodes
            WHERE session_id = 's1' AND subtype = 'context' AND valid_until IS NULL
            """
        ).fetchone()
        assert active["n"] == 1
    finally:
        conn.close()


def test_percentile_abstention_falls_back_to_absolute() -> None:
    recall = RecallConfig(
        abstain_mode="percentile",
        abstain_percentile=0.25,
        min_recall_score=5.0,
    )
    # No corpus threshold: weak match abstains via absolute fallback.
    assert should_abstain([-0.5], recall, corpus_threshold=None) is True
    assert should_abstain([-8.0], recall, corpus_threshold=None) is False


def test_context_pack_via_dispatch(runtime, tmp_path) -> None:
    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        insert_node(
            conn,
            node_id="d1",
            subtype="decision",
            title="Use FTS5",
            content="Prefer SQLite FTS5 for recall",
        )
        conn.commit()
        result = handle_context_pack(
            conn,
            ContextPackRequest(query="FTS5 recall", session_id="s-pack"),
            config=BrainConfig(recall={"abstain_on_low_confidence": False}),
            project_dir=tmp_path,
        )
        assert "Context pack" in result.pack_text
        assert result.truncation.token_budget > 0
        assert token_count(result.pack_text) <= BrainConfig().budget.total_tokens + 50
    finally:
        conn.close()


def test_recall_returns_session_chunks_field(runtime, tmp_path) -> None:
    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        insert_node(
            conn,
            node_id="r1",
            subtype="fact",
            title="graph sync",
            content="auto sync after Write",
        )
        conn.commit()
        result = handle_recall(
            conn,
            RecallRequest(query="graph sync", limit=5, session_id="s-rec"),
            config=BrainConfig(recall={"abstain_on_low_confidence": False}),
            project_dir=tmp_path,
        )
        assert hasattr(result, "session_chunks")
        assert isinstance(result.session_chunks, list)
    finally:
        conn.close()


def test_brain_stats_tool(runtime, tmp_path) -> None:
    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        insert_node(conn, node_id="s1", subtype="rule", title="rule one")
        conn.commit()
        stats = handle_brain_stats(
            conn,
            BrainStatsRequest(),
            config=BrainConfig(),
            project_dir=tmp_path,
        )
        assert stats.neurons_by_kind.get("memory", 0) >= 1
        assert stats.abstention_mode is not None
    finally:
        conn.close()


def test_graph_sync_request_only(runtime, tmp_path) -> None:
    response = handle_graph_sync(
        tmp_path,
        GraphSyncRequest(force=False),
        config=BrainConfig(graphify={"enabled": True}),
    )
    assert response.requested is True
    assert response.ran is False
    assert (tmp_path / ".brain" / "graph_sync.requested").is_file()


def test_traverse_includes_relationship(runtime, tmp_path) -> None:
    from brainkm.models.schemas import TraverseRequest
    from brainkm.tools.dispatch import handle_traverse
    from tests.conftest import insert_edge

    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        insert_node(conn, node_id="fa", kind="code", subtype="file", title="a.py", path="a.py")
        insert_node(conn, node_id="fb", kind="code", subtype="file", title="b.py", path="b.py")
        insert_edge(conn, edge_id="e1", from_id="fa", to_id="fb", relationship="imports")
        conn.commit()
        result = handle_traverse(
            conn,
            TraverseRequest(from_ref="a.py", max_hops=1, direction="out"),
            config=BrainConfig(),
        )
        match = next(n for n in result.nodes if n.node_id == "fb")
        assert match.relationship == "imports"
        assert match.via == "fa"
        assert result.hops_explored >= 1
    finally:
        conn.close()
