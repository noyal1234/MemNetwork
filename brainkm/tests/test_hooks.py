"""Tests for Cursor hook handlers."""

import json
from pathlib import Path

from brainkm.models.brain_config import BrainConfig
from brainkm.services.hooks import (
    HookRunResult,
    build_cursor_hook_stdout,
    pre_tool_matcher,
    run_pre_tool_use,
    run_session_start,
)


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
