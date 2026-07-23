"""Tests for MCP tool dispatch handlers."""

import pytest

from brainkm.db.connection import connect
from brainkm.models.brain_config import BrainConfig
from brainkm.models.schemas import (
    ForgetRequest,
    RecallRequest,
    RememberRequest,
    SessionStatusRequest,
    TraverseRequest,
)
from brainkm.services.decision_trail import should_include_history
from brainkm.services.memory import supersede_neuron
from brainkm.services.recall_limit import RecallLimitState
from brainkm.tools.dispatch import (
    BrainRuntime,
    dispatch_tool,
    handle_forget,
    handle_recall,
    handle_remember,
    handle_session_status,
    handle_traverse,
)
from tests.conftest import insert_edge, insert_node


@pytest.fixture
def runtime(tmp_path) -> BrainRuntime:
    from brainkm.db.migrate import migrate

    migrate(db_path=tmp_path / ".brain" / "brain.db", run_integrity_check=True)
    return BrainRuntime(project_dir=tmp_path)


@pytest.mark.asyncio
async def test_removed_mcp_tools_are_unknown(runtime) -> None:
    for name in ("session_status", "forget", "graph_sync"):
        with pytest.raises(ValueError, match="unknown tool"):
            await dispatch_tool(name, {}, runtime)


def test_remember_and_recall(runtime, tmp_path) -> None:
    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        response = handle_remember(
            conn,
            RememberRequest(title="Auth choice", body="JWT over session cookies for API"),
        )
        conn.commit()
        assert response.node_id
        assert response.action == "pin"

        recall = handle_recall(
            conn,
            RecallRequest(query="JWT auth", limit=5),
            config=BrainConfig(recall={"abstain_on_low_confidence": False}),
            project_dir=tmp_path,
        )
        assert len(recall.nodes) >= 1
        assert recall.confidence in {"high", "medium", "low"}
    finally:
        conn.close()


def test_remember_archive_action(runtime, tmp_path) -> None:
    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        created = handle_remember(
            conn,
            RememberRequest(title="Temp", body="Remove me"),
        )
        conn.commit()
        archived = handle_remember(
            conn,
            RememberRequest(
                action="archive",
                target_node_id=created.node_id,
                reason="test",
            ),
        )
        assert archived.action == "archive"
        assert archived.archived_node_id == created.node_id
        row = conn.execute(
            "SELECT valid_until FROM nodes WHERE id = ?", (created.node_id,)
        ).fetchone()
        assert row["valid_until"] is not None
    finally:
        conn.close()


def test_remember_correct_writes_supersedes(runtime, tmp_path) -> None:
    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        old = handle_remember(
            conn,
            RememberRequest(
                title="Use sessions",
                body="Prefer server sessions for auth",
                subtype="decision",
            ),
        )
        conn.commit()
        new = handle_remember(
            conn,
            RememberRequest(
                title="Use JWT",
                body="Prefer JWT over sessions for API auth",
                subtype="decision",
                action="correct",
                target_node_id=old.node_id,
                reason="pivoted to JWT",
            ),
        )
        assert new.superseded_node_id == old.node_id
        edge = conn.execute(
            """
            SELECT 1 FROM edges
            WHERE from_id = ? AND to_id = ? AND relationship = 'supersedes'
            """,
            (new.node_id, old.node_id),
        ).fetchone()
        assert edge is not None
        old_row = conn.execute(
            "SELECT valid_until FROM nodes WHERE id = ?", (old.node_id,)
        ).fetchone()
        assert old_row["valid_until"] is not None
    finally:
        conn.close()


def test_remember_links_code_path(runtime, tmp_path) -> None:
    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        insert_node(
            conn,
            node_id="code-memory",
            kind="code",
            subtype="file",
            title="memory.py",
            path="brainkm/services/memory.py",
        )
        conn.commit()
        resp = handle_remember(
            conn,
            RememberRequest(
                title="Token budget",
                body="Enforce 1500 tokens in brainkm/services/memory.py",
                subtype="decision",
            ),
        )
        assert "code-memory" in resp.linked_code_nodes
        edge = conn.execute(
            """
            SELECT 1 FROM edges
            WHERE from_id = ? AND to_id = ? AND relationship = 'about_file'
            """,
            (resp.node_id, "code-memory"),
        ).fetchone()
        assert edge is not None
    finally:
        conn.close()


def test_session_status_helper_still_works(runtime, tmp_path) -> None:
    """session_status remains a service helper for hooks, not an MCP tool."""
    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        written = handle_session_status(
            conn,
            SessionStatusRequest(
                session_id="s1", title="Working on auth", body="Refactoring middleware"
            ),
        )
        conn.commit()
        assert written.updated is True

        read_back = handle_session_status(conn, SessionStatusRequest(session_id="s1"))
        assert read_back.title == "Working on auth"
    finally:
        conn.close()


def test_traverse_one_hop(runtime, tmp_path) -> None:
    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        insert_node(conn, node_id="a", kind="code", subtype="file", title="a.py", path="a.py")
        insert_node(conn, node_id="b", kind="code", subtype="function", title="fn", path="a.py")
        insert_edge(conn, edge_id="e1", from_id="a", to_id="b", relationship="defines")
        conn.commit()

        result = handle_traverse(
            conn,
            TraverseRequest(from_ref="a.py", max_hops=1),
            config=BrainConfig(),
            project_dir=tmp_path,
        )
        assert result.resolved_id == "a"
        assert result.hint is None
        assert any(n.node_id == "b" for n in result.nodes)
        assert all(n.node_id != "a" for n in result.nodes)
        assert result.impact_summary is not None
        assert result.impact_summary.neighbor_count >= 1
    finally:
        conn.close()


def test_recall_and_traverse_overlays_fit_token_budget(runtime, tmp_path) -> None:
    """decision_trail / linked_neurons must share the single total_tokens budget."""
    from brainkm.services.memory import token_count

    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        old = handle_remember(
            conn,
            RememberRequest(
                title="Budget policy v1",
                body="Use a soft 2000 token pack",
                subtype="decision",
            ),
        )
        new = handle_remember(
            conn,
            RememberRequest(
                title="Budget policy v2",
                body="Use a hard 1500 token pack",
                subtype="decision",
            ),
        )
        supersede_neuron(conn, old.node_id, replacement_id=new.node_id)
        conn.commit()

        budget = 400
        recall = handle_recall(
            conn,
            RecallRequest(query="why did we choose the token budget", limit=10),
            config=BrainConfig(
                budget={"total_tokens": budget},
                recall={"abstain_on_low_confidence": False},
            ),
            project_dir=tmp_path,
        )
        nodes_tokens = sum(token_count(f"{n.title}\n{n.content or ''}") for n in recall.nodes)
        trail_tokens = sum(
            token_count(f"{e.title}\n{e.subtype or ''}") for e in recall.decision_trail
        )
        assert nodes_tokens + trail_tokens <= budget

        insert_node(conn, node_id="fn", kind="code", subtype="function", title="budget_fn")
        insert_node(conn, node_id="caller", kind="code", subtype="function", title="caller_fn")
        insert_edge(conn, edge_id="e1", from_id="caller", to_id="fn", relationship="calls")
        insert_edge(
            conn,
            edge_id="e2",
            from_id=new.node_id,
            to_id="caller",
            relationship="about_symbol",
        )
        conn.commit()

        traverse = handle_traverse(
            conn,
            TraverseRequest(from_ref="budget_fn", max_hops=1),
            config=BrainConfig(budget={"total_tokens": budget}),
            project_dir=tmp_path,
        )
        graph_tokens = sum(token_count(f"{n.title}\n{n.content or ''}") for n in traverse.nodes)
        linked_tokens = sum(
            token_count(f"{n.title}\n{n.content or ''}") for n in traverse.linked_neurons
        )
        assert graph_tokens + linked_tokens <= budget
    finally:
        conn.close()


def test_traverse_linked_neurons(runtime, tmp_path) -> None:
    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        insert_node(conn, node_id="fn", kind="code", subtype="function", title="target_fn")
        insert_node(conn, node_id="caller", kind="code", subtype="function", title="caller_fn")
        insert_edge(
            conn,
            edge_id="e1",
            from_id="caller",
            to_id="fn",
            relationship="calls",
        )
        mem = handle_remember(
            conn,
            RememberRequest(
                title="Do not break callers",
                body="caller_fn depends on target_fn contract",
                subtype="decision",
            ),
        )
        # Force about_symbol edge to the impacted neighbor
        insert_edge(
            conn,
            edge_id="e2",
            from_id=mem.node_id,
            to_id="caller",
            relationship="about_symbol",
        )
        conn.commit()

        result = handle_traverse(
            conn,
            TraverseRequest(from_ref="target_fn", max_hops=1),
            config=BrainConfig(),
            project_dir=tmp_path,
        )
        assert any(n.node_id == mem.node_id for n in result.linked_neurons)
    finally:
        conn.close()


def test_traverse_unresolved_returns_hint(runtime, tmp_path) -> None:
    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        result = handle_traverse(
            conn,
            TraverseRequest(from_ref="NonExistentSymbolXYZ"),
            config=BrainConfig(),
            project_dir=tmp_path,
        )
        assert result.nodes == []
        assert result.resolved_id is None
        assert result.hint is not None
        assert "from_ref" in result.hint
        assert "graph_sync" not in result.hint  # MCP tool removed
    finally:
        conn.close()


def test_traverse_default_both_finds_callers(runtime, tmp_path) -> None:
    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        insert_node(conn, node_id="target", kind="code", subtype="function", title="target_fn")
        insert_node(conn, node_id="caller", kind="code", subtype="function", title="caller_fn")
        insert_edge(
            conn,
            edge_id="e1",
            from_id="caller",
            to_id="target",
            relationship="calls",
        )
        conn.commit()

        result = handle_traverse(
            conn,
            TraverseRequest(from_ref="target_fn", max_hops=1),
            config=BrainConfig(),
            project_dir=tmp_path,
        )
        assert result.resolved_id == "target"
        assert any(n.node_id == "caller" for n in result.nodes)
    finally:
        conn.close()


def test_traverse_skips_references_by_default(runtime, tmp_path) -> None:
    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        insert_node(conn, node_id="fn", kind="code", subtype="function", title="fn")
        insert_node(conn, node_id="ref", kind="code", subtype="class", title="RefOnly")
        insert_node(conn, node_id="callee", kind="code", subtype="function", title="callee")
        insert_edge(conn, edge_id="e1", from_id="fn", to_id="ref", relationship="references")
        insert_edge(conn, edge_id="e2", from_id="fn", to_id="callee", relationship="calls")
        conn.commit()

        default = handle_traverse(
            conn,
            TraverseRequest(from_ref="fn", max_hops=1),
            config=BrainConfig(),
            project_dir=tmp_path,
        )
        assert {n.node_id for n in default.nodes} == {"callee"}

        all_edges = handle_traverse(
            conn,
            TraverseRequest(from_ref="fn", max_hops=1, relationship="*"),
            config=BrainConfig(),
            project_dir=tmp_path,
        )
        assert {n.node_id for n in all_edges.nodes} == {"callee", "ref"}
    finally:
        conn.close()


def test_forget_helper_soft_archives(runtime, tmp_path) -> None:
    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        created = handle_remember(
            conn,
            RememberRequest(title="Temp", body="Remove me"),
        )
        conn.commit()
        archived = handle_forget(conn, ForgetRequest(node_id=created.node_id, reason="test"))
        assert archived.archived is True
        assert archived.valid_until is not None
    finally:
        conn.close()


def test_recall_decision_trail_auto_on_temporal_intent(runtime, tmp_path) -> None:
    """Temporal intents auto-attach decision_trail without include_history=True."""
    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        old = handle_remember(
            conn,
            RememberRequest(
                title="Auth: sessions",
                body="Use server sessions",
                subtype="decision",
            ),
        )
        newest = handle_remember(
            conn,
            RememberRequest(
                title="Auth: JWT",
                body="Use JWT for API auth",
                subtype="decision",
            ),
        )
        supersede_neuron(conn, old.node_id, replacement_id=newest.node_id)
        conn.commit()

        recall = handle_recall(
            conn,
            RecallRequest(query="what was the previous auth history for JWT", limit=5),
            config=BrainConfig(recall={"abstain_on_low_confidence": False}),
            project_dir=tmp_path,
        )
        assert recall.intent == "temporal" or should_include_history(
            include_history=None, intent=recall.intent, query=recall.query
        )
        ids = [e.node_id for e in recall.decision_trail]
        assert newest.node_id in ids
        assert old.node_id in ids
    finally:
        conn.close()


def test_recall_decision_trail(runtime, tmp_path) -> None:
    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        old = handle_remember(
            conn,
            RememberRequest(
                title="Auth: sessions",
                body="Use server sessions",
                subtype="decision",
            ),
        )
        mid = handle_remember(
            conn,
            RememberRequest(
                title="Auth: cookies",
                body="Use cookie sessions",
                subtype="decision",
            ),
        )
        newest = handle_remember(
            conn,
            RememberRequest(
                title="Auth: JWT",
                body="Use JWT for API auth",
                subtype="decision",
            ),
        )
        supersede_neuron(conn, old.node_id, replacement_id=mid.node_id)
        supersede_neuron(conn, mid.node_id, replacement_id=newest.node_id)
        conn.commit()

        recall = handle_recall(
            conn,
            RecallRequest(query="why did we choose JWT auth", limit=5, include_history=True),
            config=BrainConfig(recall={"abstain_on_low_confidence": False}),
            project_dir=tmp_path,
        )
        ids = [e.node_id for e in recall.decision_trail]
        assert newest.node_id in ids
        # Trail should include superseded ancestors
        assert old.node_id in ids or mid.node_id in ids
        # Newest first
        assert ids[0] == newest.node_id or newest.node_id in ids[:2]
    finally:
        conn.close()


def test_recall_rate_limit() -> None:
    state = RecallLimitState()
    cfg = BrainConfig(injection={"max_recalls_per_turn": 1})
    assert state.check("s1", cfg) is True
    assert state.check("s1", cfg) is False
    assert state.check("s1", cfg, truncation_followup=True) is True


def test_recall_rate_limit_anonymous_not_shared() -> None:
    """Clients omitting session_id must not share one global bucket."""
    state = RecallLimitState()
    cfg = BrainConfig(injection={"max_recalls_per_turn": 1})
    assert state.check(None, cfg) is True
    assert state.check(None, cfg) is True
    assert state.check("s1", cfg) is True
    assert state.check("s1", cfg) is False


def test_traverse_request_accepts_query_symbol_path_aliases() -> None:
    assert TraverseRequest.model_validate({"query": "run_install"}).from_ref == "run_install"
    assert TraverseRequest.model_validate({"symbol": "Foo.bar"}).from_ref == "Foo.bar"
    assert TraverseRequest.model_validate({"path": "a.py"}).from_ref == "a.py"
    # Canonical wins over aliases.
    assert TraverseRequest.model_validate({"from_ref": "keep", "query": "other"}).from_ref == "keep"


def test_remember_request_accepts_content_text_aliases() -> None:
    req = RememberRequest.model_validate({"title": "Auth", "content": "Use JWT for API auth"})
    assert req.body == "Use JWT for API auth"
    req2 = RememberRequest.model_validate(
        {"name": "Rule", "text": "Never store secrets in neurons"}
    )
    assert req2.title == "Rule"
    assert req2.body == "Never store secrets in neurons"
    # Last-resort title from body first line.
    req3 = RememberRequest.model_validate({"content": "Chose SQLite for V1 local brain storage."})
    assert req3.body.startswith("Chose SQLite")
    assert req3.title.startswith("Chose SQLite")
