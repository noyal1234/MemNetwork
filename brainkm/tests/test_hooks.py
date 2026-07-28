"""Tests for Cursor hook handlers."""

import json
import sqlite3
from pathlib import Path

from brainkm.db.connection import connect
from brainkm.db.migrate import migrate
from brainkm.db.paths import brain_db_path
from brainkm.models.brain_config import BrainConfig
from brainkm.services.hooks import (
    HookRunResult,
    build_claude_hook_stdout,
    build_cursor_hook_stdout,
    pre_tool_matcher,
    run_pre_tool_use,
    run_session_start,
    run_user_prompt_submit,
)
from brainkm.services.memory import new_ulid
from brainkm.services.snapshot import _graph_status_line


def test_pre_tool_matcher_from_config() -> None:
    matcher = pre_tool_matcher(["write", "edit", "run_terminal"])
    assert matcher == "Write|Edit|Shell"


def test_run_session_start_migrates_db(tmp_path: Path) -> None:
    db_path = tmp_path / ".brain" / "brain.db"
    result = run_session_start(
        json.dumps({"session_id": "sess-1"}),
        project_dir=tmp_path,
        config=BrainConfig(),
    )
    assert result.skipped is False
    assert db_path.is_file()


def test_run_pre_tool_use_matches_write(tmp_path: Path) -> None:
    result = run_pre_tool_use(
        json.dumps({"tool_name": "Write", "session_id": "s1"}),
        project_dir=tmp_path,
        config=BrainConfig(),
    )
    assert result.skipped is True
    assert result.reason == "no meaningful pre-tool seed"


def test_run_pre_tool_use_skips_unmatched_tool() -> None:
    result = run_pre_tool_use(
        json.dumps({"tool_name": "Read", "session_id": "s1"}),
        config=BrainConfig(),
    )
    assert result.skipped is True
    assert result.reason == "tool not matched"


def test_run_session_start_respects_disabled_injection(tmp_path: Path) -> None:
    result = run_session_start(
        "{}",
        project_dir=tmp_path,
        config=BrainConfig(injection={"session_start": False}),
    )
    assert result.skipped is True
    assert not (tmp_path / ".brain" / "brain.db").exists()


def test_build_cursor_hook_stdout_pre_tool_allow_when_skipped() -> None:
    result = HookRunResult(
        hook="PreToolUse",
        session_id="s1",
        skipped=True,
        reason="tool not matched",
    )
    assert build_cursor_hook_stdout(result, "preToolUse") == {"permission": "allow"}


def test_build_cursor_hook_stdout_pre_tool_injects_agent_message() -> None:
    result = HookRunResult(
        hook="PreToolUse",
        session_id="s1",
        skipped=False,
        reason=None,
        additional_context="Context pack for auth middleware",
    )
    assert build_cursor_hook_stdout(result, "preToolUse") == {
        "permission": "allow",
        "agent_message": "Context pack for auth middleware",
    }


def test_build_cursor_hook_stdout_session_start_empty_when_no_context() -> None:
    result = HookRunResult(
        hook="SessionStart",
        session_id="s1",
        skipped=True,
        reason="injection.session_start disabled",
    )
    assert build_cursor_hook_stdout(result, "sessionStart") == {}


def test_build_cursor_hook_stdout_post_tool_additional_context() -> None:
    result = HookRunResult(
        hook="PostToolUse",
        session_id="s1",
        skipped=False,
        reason=None,
        additional_context="refreshed graph",
    )
    assert build_cursor_hook_stdout(result, "postToolUse") == {
        "additional_context": "refreshed graph",
    }


def _seed_completed_graph_import(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT INTO graph_import_runs (id, started_at, completed_at, status, node_count, edge_count)
        VALUES (?, datetime('now'), datetime('now'), 'completed', 1, 0)
        """,
        (new_ulid(),),
    )
    conn.commit()


def test_graph_status_line_mentions_deferred_tools_and_session_id(tmp_path: Path) -> None:
    run_session_start(
        json.dumps({"session_id": "sess-graph"}),
        project_dir=tmp_path,
        config=BrainConfig(),
    )
    conn = connect(brain_db_path(tmp_path))
    try:
        _seed_completed_graph_import(conn)
        line = _graph_status_line(conn, "sess-graph")
    finally:
        conn.close()
    assert line is not None
    assert "ToolSearch" in line
    assert "mcp__brainkm__traverse" in line
    assert 'session_id="sess-graph"' in line


def test_user_prompt_submit_nudge_fires_on_first_prompt(tmp_path: Path) -> None:
    migrate(project_dir=tmp_path, run_integrity_check=False)
    result = run_user_prompt_submit(
        json.dumps({"session_id": "sess-nudge", "prompt": "why did we pick X"}),
        project_dir=tmp_path,
        config=BrainConfig(),
    )
    assert result.additional_context is not None
    assert "sess-nudge" in result.additional_context
    assert "ToolSearch" in result.additional_context


def test_user_prompt_submit_nudge_fires_even_when_auto_observe_disabled(tmp_path: Path) -> None:
    migrate(project_dir=tmp_path, run_integrity_check=False)
    result = run_user_prompt_submit(
        json.dumps({"session_id": "sess-nudge-2", "prompt": "why did we pick X"}),
        project_dir=tmp_path,
        config=BrainConfig(capture={"auto_observe": False}),
    )
    assert result.reason == "auto_observe disabled"
    assert result.additional_context is not None
    assert "sess-nudge-2" in result.additional_context


def test_user_prompt_submit_nudge_suppressed_once_brainkm_used(tmp_path: Path) -> None:
    session_id = "sess-used"
    migrate(project_dir=tmp_path, run_integrity_check=False)
    conn = connect(brain_db_path(tmp_path))
    try:
        conn.execute(
            """
            INSERT INTO session_activity (id, session_id, kind, node_id, tool_name, source, created_at)
            VALUES (?, ?, 'tool_use', NULL, 'traverse', 'mcp', datetime('now'))
            """,
            (new_ulid(), session_id),
        )
        conn.commit()
    finally:
        conn.close()

    result = run_user_prompt_submit(
        json.dumps({"session_id": session_id, "prompt": "what calls foo"}),
        project_dir=tmp_path,
        config=BrainConfig(),
    )
    assert result.additional_context is None


def test_user_prompt_submit_nudge_capped_per_session(tmp_path: Path) -> None:
    session_id = "sess-capped"
    migrate(project_dir=tmp_path, run_integrity_check=False)
    cfg = BrainConfig(injection={"routing_nudge_max_per_session": 1})

    first = run_user_prompt_submit(
        json.dumps({"session_id": session_id, "prompt": "first prompt"}),
        project_dir=tmp_path,
        config=cfg,
    )
    assert first.additional_context is not None

    second = run_user_prompt_submit(
        json.dumps({"session_id": session_id, "prompt": "second prompt"}),
        project_dir=tmp_path,
        config=cfg,
    )
    assert second.additional_context is None


def test_user_prompt_submit_nudge_disabled_via_config(tmp_path: Path) -> None:
    result = run_user_prompt_submit(
        json.dumps({"session_id": "sess-off", "prompt": "why did we pick X"}),
        project_dir=tmp_path,
        config=BrainConfig(injection={"routing_nudge": False}),
    )
    assert result.additional_context is None


def test_build_claude_hook_stdout_user_prompt_submit_injects_context() -> None:
    result = HookRunResult(
        hook="UserPromptSubmit",
        session_id="s1",
        skipped=False,
        reason=None,
        additional_context="brainkm reminder text",
    )
    payload = build_claude_hook_stdout(result, "userPromptSubmit")
    assert payload == {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "brainkm reminder text",
        }
    }
