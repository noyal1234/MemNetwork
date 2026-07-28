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


def test_run_pre_tool_use_skips_unmatched_tool(tmp_path: Path) -> None:
    result = run_pre_tool_use(
        json.dumps({"tool_name": "WebSearch", "session_id": "s1"}),
        project_dir=tmp_path,
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


def test_graph_status_line_has_session_id_without_toolsearch(tmp_path: Path) -> None:
    run_session_start(
        json.dumps({"session_id": "sess-graph"}),
        project_dir=tmp_path,
        config=BrainConfig(),
        client="claude",
    )
    conn = connect(brain_db_path(tmp_path))
    try:
        _seed_completed_graph_import(conn)
        line = _graph_status_line(conn, "sess-graph")
    finally:
        conn.close()
    assert line is not None
    assert "ToolSearch" not in line
    assert "traverse" in line
    assert 'session_id="sess-graph"' in line


def test_session_start_claude_pack_has_toolsearch_lead_in(tmp_path: Path) -> None:
    result = run_session_start(
        json.dumps({"session_id": "sess-lead"}),
        project_dir=tmp_path,
        config=BrainConfig(),
        client="claude",
    )
    assert result.additional_context is not None
    assert "Load brainkm tools first" in result.additional_context
    assert "ToolSearch" in result.additional_context
    assert "Frozen at session start" in result.additional_context
    assert "mcp__brainkm__recall" in result.additional_context


def test_session_start_cursor_pack_omits_toolsearch(tmp_path: Path) -> None:
    result = run_session_start(
        json.dumps({"session_id": "sess-cursor-pack"}),
        project_dir=tmp_path,
        config=BrainConfig(),
        client="cursor",
    )
    assert result.additional_context is not None
    assert "ToolSearch" not in result.additional_context
    assert "Frozen at session start" in result.additional_context


def test_graph_status_line_omits_toolsearch_for_cursor(tmp_path: Path) -> None:
    run_session_start(
        json.dumps({"session_id": "sess-cursor-graph"}),
        project_dir=tmp_path,
        config=BrainConfig(),
        client="cursor",
    )
    conn = connect(brain_db_path(tmp_path))
    try:
        _seed_completed_graph_import(conn)
        line = _graph_status_line(conn, "sess-cursor-graph", client="cursor")
    finally:
        conn.close()
    assert line is not None
    assert "ToolSearch" not in line
    assert "traverse" in line
    assert 'session_id="sess-cursor-graph"' in line


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


def test_user_prompt_submit_nudge_skipped_for_cursor(tmp_path: Path) -> None:
    migrate(project_dir=tmp_path, run_integrity_check=False)
    result = run_user_prompt_submit(
        json.dumps({"session_id": "sess-cursor-nudge", "prompt": "why did we pick X"}),
        project_dir=tmp_path,
        config=BrainConfig(),
        client="cursor",
    )
    assert result.additional_context is None
    conn = connect(brain_db_path(tmp_path))
    try:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM session_activity "
            "WHERE session_id = ? AND kind = 'routing_nudge'",
            ("sess-cursor-nudge",),
        ).fetchone()["c"]
    finally:
        conn.close()
    assert count == 0


def test_user_prompt_submit_nudge_skipped_for_antigravity(tmp_path: Path) -> None:
    migrate(project_dir=tmp_path, run_integrity_check=False)
    result = run_user_prompt_submit(
        json.dumps({"session_id": "sess-agy-nudge", "prompt": "why did we pick X"}),
        project_dir=tmp_path,
        config=BrainConfig(),
        client="antigravity",
    )
    assert result.additional_context is None


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
    migrate(project_dir=tmp_path, run_integrity_check=False)
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


def test_pre_tool_read_triggers_routing_nudge(tmp_path: Path) -> None:
    migrate(project_dir=tmp_path, run_integrity_check=False)
    result = run_pre_tool_use(
        json.dumps({"tool_name": "Read", "session_id": "sess-read-nudge"}),
        project_dir=tmp_path,
        config=BrainConfig(),
        client="claude",
    )
    assert result.skipped is False
    assert result.additional_context is not None
    assert "ToolSearch" in result.additional_context


def test_pre_tool_read_nudge_skipped_for_cursor(tmp_path: Path) -> None:
    migrate(project_dir=tmp_path, run_integrity_check=False)
    result = run_pre_tool_use(
        json.dumps({"tool_name": "Read", "session_id": "sess-read-cursor"}),
        project_dir=tmp_path,
        config=BrainConfig(),
        client="cursor",
    )
    assert result.additional_context is None
    assert result.skipped is True


def test_routing_nudge_rearms_after_drift(tmp_path: Path) -> None:
    session_id = "sess-rearm"
    migrate(project_dir=tmp_path, run_integrity_check=False)
    cfg = BrainConfig(
        injection={
            "routing_nudge_rearm_after_calls": 3,
            "routing_nudge_max_per_session": 5,
        }
    )
    conn = connect(brain_db_path(tmp_path))
    try:
        conn.execute(
            """
            INSERT INTO session_activity (id, session_id, kind, node_id, tool_name, source, created_at)
            VALUES (?, ?, 'tool_use', NULL, 'recall', 'mcp', datetime('now', '-1 minute'))
            """,
            (new_ulid(), session_id),
        )
        for i in range(3):
            conn.execute(
                """
                INSERT INTO session_activity (id, session_id, kind, node_id, tool_name, source, created_at)
                VALUES (?, ?, 'tool_use', NULL, 'Read', 'post_tool', datetime('now'))
                """,
                (new_ulid(), session_id),
            )
        conn.commit()
    finally:
        conn.close()

    result = run_user_prompt_submit(
        json.dumps({"session_id": session_id, "prompt": "still editing"}),
        project_dir=tmp_path,
        config=cfg,
        client="claude",
    )
    assert result.additional_context is not None
    assert "REQUIRED" in result.additional_context or "ToolSearch" in result.additional_context


def test_pre_tool_matcher_includes_read_patterns() -> None:
    matcher = pre_tool_matcher(["write", "edit", "read", "grep", "glob"])
    assert matcher == "Write|Edit|Read|Grep|Glob"


def test_claude_rules_template_has_no_paths_frontmatter() -> None:
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[1]
        / "brainkm"
        / "hooks"
        / "claude"
        / "rules"
        / "brainkm.md"
    )
    text = path.read_text(encoding="utf-8")
    assert not text.lstrip().startswith("---")
    assert "\npaths:" not in text and not text.startswith("paths:")
