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
from brainkm.services.recall_limit import RecallLimitState
from brainkm.tools.dispatch import (
    BrainRuntime,
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


def test_remember_and_recall(runtime, tmp_path) -> None:
    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        response = handle_remember(
            conn,
            RememberRequest(title="Auth choice", body="JWT over session cookies for API"),
            config=BrainConfig(),
        )
        conn.commit()
        assert response.node_id

        recall = handle_recall(
            conn,
            RecallRequest(query="JWT auth", limit=5),
            config=BrainConfig(recall={"abstain_on_low_confidence": False}),
            project_dir=tmp_path,
        )
        assert len(recall.nodes) >= 1
    finally:
        conn.close()


def test_session_status_write_read(runtime, tmp_path) -> None:
    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        written = handle_session_status(
            conn,
            SessionStatusRequest(session_id="s1", title="Working on auth", body="Refactoring middleware"),
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
        )
        assert any(n.node_id == "b" for n in result.nodes)
    finally:
        conn.close()


def test_forget_soft_archives(runtime, tmp_path) -> None:
    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        created = handle_remember(
            conn,
            RememberRequest(title="Temp", body="Remove me"),
            config=BrainConfig(),
        )
        conn.commit()
        archived = handle_forget(conn, ForgetRequest(node_id=created.node_id, reason="test"))
        assert archived.archived is True
        assert archived.valid_until is not None
    finally:
        conn.close()


def test_recall_rate_limit() -> None:
    state = RecallLimitState()
    cfg = BrainConfig(injection={"max_recalls_per_turn": 1})
    assert state.check("s1", cfg) is True
    assert state.check("s1", cfg) is False
    assert state.check("s1", cfg, truncation_followup=True) is True
