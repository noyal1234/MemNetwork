"""Tests for PreToolUse context_pack hook."""

import json

from brainkm.db.connection import connect
from brainkm.models.brain_config import BrainConfig
from brainkm.services.hooks import run_pre_tool_use
from tests.conftest import insert_node


def test_pre_tool_use_skips_without_seed(brain_db) -> None:
    project_dir = brain_db.parent.parent
    payload = json.dumps({"tool_name": "Shell", "tool_input": {}})
    result = run_pre_tool_use(payload, project_dir=project_dir, config=BrainConfig())
    assert result.skipped is True


def test_pre_tool_use_injects_context_pack(brain_db) -> None:
    project_dir = brain_db.parent.parent
    conn = connect(brain_db)
    try:
        insert_node(
            conn,
            node_id="auth",
            subtype="decision",
            title="JWT middleware path",
            content="See src/auth/middleware.py",
        )
        conn.commit()
    finally:
        conn.close()

    payload = json.dumps(
        {
            "tool_name": "Edit",
            "tool_input": {"path": "src/auth/middleware.py"},
            "session_id": "sess-1",
        }
    )
    result = run_pre_tool_use(payload, project_dir=project_dir, config=BrainConfig())
    assert result.skipped is False
    assert result.additional_context is not None
    assert "Context pack" in result.additional_context
