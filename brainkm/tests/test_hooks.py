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
    build_codex_hook_stdout,
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


def _git_history_payload(command: str) -> str:
    return json.dumps(
        {"tool_name": "Bash", "session_id": "s1", "tool_input": {"command": command}}
    )


def test_pre_tool_denies_single_file_git_history(tmp_path: Path) -> None:
    """Single-file `git log` is exactly trace_changes — deny, don't merely nudge."""
    target = tmp_path / "svc.py"
    target.write_text("x = 1\n", encoding="utf-8")
    result = run_pre_tool_use(
        _git_history_payload("git log --oneline svc.py"),
        project_dir=tmp_path,
        config=BrainConfig(),
        client="claude",
    )
    assert result.deny_reason is not None
    assert "trace_changes" in result.deny_reason
    out = build_claude_hook_stdout(result, "preToolUse")
    assert out is not None
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert out["hookSpecificOutput"]["permissionDecisionReason"] == result.deny_reason


def test_pre_tool_allows_git_history_asking_for_diff_text(tmp_path: Path) -> None:
    """trace_changes leaves diffs in git, so -p must stay reachable."""
    (tmp_path / "svc.py").write_text("x = 1\n", encoding="utf-8")
    result = run_pre_tool_use(
        _git_history_payload("git log -p svc.py"),
        project_dir=tmp_path,
        config=BrainConfig(),
        client="claude",
    )
    assert result.deny_reason is None


def test_pre_tool_allows_whole_commit_git_show(tmp_path: Path) -> None:
    """`git show --stat <sha>` spans many files — not a trace_changes question."""
    result = run_pre_tool_use(
        _git_history_payload("git show --stat 1a89fb1"),
        project_dir=tmp_path,
        config=BrainConfig(),
        client="claude",
    )
    assert result.deny_reason is None


def test_pre_tool_deny_ignores_git_inside_quoted_argument(tmp_path: Path) -> None:
    """`git log` inside a quoted string is data, not an invocation."""
    (tmp_path / "svc.py").write_text("x = 1\n", encoding="utf-8")
    result = run_pre_tool_use(
        _git_history_payload("""echo '{"command": "git log svc.py"}' | some-tool --stdin"""),
        project_dir=tmp_path,
        config=BrainConfig(),
        client="claude",
    )
    assert result.deny_reason is None


def test_pre_tool_deny_ignores_grep_for_git_log_literal(tmp_path: Path) -> None:
    (tmp_path / "svc.py").write_text("x = 1\n", encoding="utf-8")
    result = run_pre_tool_use(
        _git_history_payload('grep -n "git log" svc.py'),
        project_dir=tmp_path,
        config=BrainConfig(),
        client="claude",
    )
    assert result.deny_reason is None


def test_pre_tool_deny_never_blocks_unparseable_command(tmp_path: Path) -> None:
    """Unbalanced quotes must fail open, not block the agent."""
    (tmp_path / "svc.py").write_text("x = 1\n", encoding="utf-8")
    result = run_pre_tool_use(
        _git_history_payload("git log svc.py 'unbalanced"),
        project_dir=tmp_path,
        config=BrainConfig(),
        client="claude",
    )
    assert result.deny_reason is None


def test_pre_tool_denies_git_history_in_a_pipeline(tmp_path: Path) -> None:
    (tmp_path / "svc.py").write_text("x = 1\n", encoding="utf-8")
    result = run_pre_tool_use(
        _git_history_payload("git log svc.py | head -20"),
        project_dir=tmp_path,
        config=BrainConfig(),
        client="claude",
    )
    assert result.deny_reason is not None


def test_pre_tool_deny_extends_to_cursor_and_codex(tmp_path: Path) -> None:
    """P6: Cursor and Codex both have a real deny channel (permission=deny /
    permissionDecision=deny), so the redundant-git-history deny applies to
    them the same as Claude — this behavior was extended deliberately.
    """
    (tmp_path / "svc.py").write_text("x = 1\n", encoding="utf-8")
    for client in ("cursor", "codex"):
        result = run_pre_tool_use(
            _git_history_payload("git log --oneline svc.py"),
            project_dir=tmp_path,
            config=BrainConfig(),
            client=client,
        )
        assert result.deny_reason is not None, client
        assert "trace_changes" in result.deny_reason


def test_pre_tool_deny_excludes_antigravity(tmp_path: Path) -> None:
    """Antigravity's `decision` field semantics for this case are the least
    documented of the four hosts — a wrong value risks hanging the turn
    rather than cleanly declining the call, so it stays excluded.
    """
    (tmp_path / "svc.py").write_text("x = 1\n", encoding="utf-8")
    result = run_pre_tool_use(
        _git_history_payload("git log --oneline svc.py"),
        project_dir=tmp_path,
        config=BrainConfig(),
        client="antigravity",
    )
    assert result.deny_reason is None


def test_pre_tool_deny_respects_config_opt_out(tmp_path: Path) -> None:
    (tmp_path / "svc.py").write_text("x = 1\n", encoding="utf-8")
    config = BrainConfig()
    config.injection.deny_redundant_shell = False
    result = run_pre_tool_use(
        _git_history_payload("git log --oneline svc.py"),
        project_dir=tmp_path,
        config=config,
        client="claude",
    )
    assert result.deny_reason is None


def test_run_pre_tool_use_skips_unmatched_tool(tmp_path: Path) -> None:
    result = run_pre_tool_use(
        json.dumps({"tool_name": "WebSearch", "session_id": "s1"}),
        project_dir=tmp_path,
        config=BrainConfig(),
    )
    assert result.skipped is True
    assert result.reason == "tool not matched"


def test_run_session_start_resume_skips_reinjection_of_seen_pack(tmp_path: Path) -> None:
    """A 'resume' reusing a session_id whose snapshot already exists must not
    re-inject the identical pack — the resumed transcript already saw it."""
    first = run_session_start(
        json.dumps({"session_id": "sess-resume-1", "source": "startup"}),
        project_dir=tmp_path,
        config=BrainConfig(),
    )
    assert first.skipped is False

    resumed = run_session_start(
        json.dumps({"session_id": "sess-resume-1", "source": "resume"}),
        project_dir=tmp_path,
        config=BrainConfig(),
    )
    assert resumed.additional_context is None


def test_run_session_start_startup_always_injects_even_with_prior_snapshot(
    tmp_path: Path,
) -> None:
    """Only source=resume is suppressed — a fresh startup with a stale/reused
    session_id must still get its pack (no false suppression)."""
    run_session_start(
        json.dumps({"session_id": "sess-startup-1", "source": "startup"}),
        project_dir=tmp_path,
        config=BrainConfig(),
    )
    second = run_session_start(
        json.dumps({"session_id": "sess-startup-1", "source": "startup"}),
        project_dir=tmp_path,
        config=BrainConfig(),
    )
    assert second.additional_context is not None


def test_run_session_start_resume_on_new_session_id_still_injects(tmp_path: Path) -> None:
    """resume with no prior snapshot for this session_id (first time brainkm has
    seen it) must not be suppressed — nothing has been shown yet."""
    result = run_session_start(
        json.dumps({"session_id": "sess-resume-first-time", "source": "resume"}),
        project_dir=tmp_path,
        config=BrainConfig(),
    )
    assert result.additional_context is not None


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


def test_build_cursor_hook_stdout_pre_tool_deny() -> None:
    result = HookRunResult(
        hook="PreToolUse",
        session_id="s1",
        skipped=False,
        reason="redundant with trace_changes",
        deny_reason="brainkm: use trace_changes for single-file history, not `git log svc.py`.",
    )
    assert build_cursor_hook_stdout(result, "preToolUse") == {
        "permission": "deny",
        "agent_message": result.deny_reason,
    }


def test_build_codex_hook_stdout_pre_tool_deny() -> None:
    result = HookRunResult(
        hook="PreToolUse",
        session_id="s1",
        skipped=False,
        reason="redundant with trace_changes",
        deny_reason="brainkm: use trace_changes for single-file history, not `git log svc.py`.",
    )
    assert build_codex_hook_stdout(result, "preToolUse") == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": result.deny_reason,
        },
        "continue": True,
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


def test_toolsearch_select_covers_every_rule_mandated_tool() -> None:
    """P2: the ToolSearch select string must load every tool the routing rules
    tell Claude to call without a second ToolSearch — previously `feedback`
    was mandated by brainkm.md but missing from the select list.
    """
    from brainkm.services.snapshot import _TOOL_SEARCH_SELECT

    for tool in (
        "recall",
        "traverse",
        "context_pack",
        "brain_stats",
        "remember",
        "trace_changes",
        "feedback",
    ):
        assert f"mcp__brainkm__{tool}" in _TOOL_SEARCH_SELECT
    # checkpoint is deliberately excluded (Claude has native PreCompact).
    assert "mcp__brainkm__checkpoint" not in _TOOL_SEARCH_SELECT


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


def test_session_start_without_client_omits_toolsearch(tmp_path: Path) -> None:
    """Missing --client must not inherit Claude ToolSearch lead_in."""
    result = run_session_start(
        json.dumps({"session_id": "sess-no-client"}),
        project_dir=tmp_path,
        config=BrainConfig(),
    )
    assert result.additional_context is not None
    assert "ToolSearch" not in result.additional_context
    assert "Frozen at session start" in result.additional_context


def test_user_prompt_submit_nudge_fires_on_first_prompt(tmp_path: Path) -> None:
    migrate(project_dir=tmp_path, run_integrity_check=False)
    result = run_user_prompt_submit(
        json.dumps({"session_id": "sess-nudge", "prompt": "why did we pick X"}),
        project_dir=tmp_path,
        config=BrainConfig(),
        client="claude",
    )
    assert result.additional_context is not None
    assert "sess-nudge" in result.additional_context
    assert "ToolSearch" in result.additional_context


def test_user_prompt_submit_nudge_skipped_without_client(tmp_path: Path) -> None:
    migrate(project_dir=tmp_path, run_integrity_check=False)
    result = run_user_prompt_submit(
        json.dumps({"session_id": "sess-none-nudge", "prompt": "why did we pick X"}),
        project_dir=tmp_path,
        config=BrainConfig(),
    )
    assert result.additional_context is None


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
        client="claude",
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
        client="claude",
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
        client="claude",
    )
    assert first.additional_context is not None

    second = run_user_prompt_submit(
        json.dumps({"session_id": session_id, "prompt": "second prompt"}),
        project_dir=tmp_path,
        config=cfg,
        client="claude",
    )
    assert second.additional_context is None


def test_user_prompt_submit_nudge_disabled_via_config(tmp_path: Path) -> None:
    migrate(project_dir=tmp_path, run_integrity_check=False)
    result = run_user_prompt_submit(
        json.dumps({"session_id": "sess-off", "prompt": "why did we pick X"}),
        project_dir=tmp_path,
        config=BrainConfig(injection={"routing_nudge": False}),
        client="claude",
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
    # Drift copy must route to the tools without claiming they are unloaded —
    # the agent can see that it already called them, and a falsifiable nudge
    # is one it learns to ignore.
    assert "trace_changes" in result.additional_context
    assert "already loaded" in result.additional_context
    assert "not loaded" not in result.additional_context


def _seed_drift_activity(tmp_path: Path, session_id: str, *, drift_calls: int = 3) -> None:
    conn = connect(brain_db_path(tmp_path))
    try:
        conn.execute(
            """
            INSERT INTO session_activity (id, session_id, kind, node_id, tool_name, source, created_at)
            VALUES (?, ?, 'tool_use', NULL, 'recall', 'mcp', datetime('now', '-1 minute'))
            """,
            (new_ulid(), session_id),
        )
        for _ in range(drift_calls):
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


def test_drift_nudge_fires_for_cursor_without_toolsearch_copy(tmp_path: Path) -> None:
    """P10: the drift nudge ('N tool calls since your last brainkm call') names
    no ToolSearch step and is host-neutral — it must not be suppressed by the
    Claude-only gate that guards the 'tools not loaded' copy.
    """
    session_id = "sess-drift-cursor"
    migrate(project_dir=tmp_path, run_integrity_check=False)
    cfg = BrainConfig(
        injection={"routing_nudge_rearm_after_calls": 3, "routing_nudge_max_per_session": 5}
    )
    _seed_drift_activity(tmp_path, session_id, drift_calls=3)

    result = run_user_prompt_submit(
        json.dumps({"session_id": session_id, "prompt": "still editing"}),
        project_dir=tmp_path,
        config=cfg,
        client="cursor",
    )
    assert result.additional_context is not None
    assert "ToolSearch" not in result.additional_context
    assert "already loaded" in result.additional_context


def test_drift_nudge_fires_for_antigravity_without_toolsearch_copy(tmp_path: Path) -> None:
    session_id = "sess-drift-agy"
    migrate(project_dir=tmp_path, run_integrity_check=False)
    cfg = BrainConfig(
        injection={"routing_nudge_rearm_after_calls": 3, "routing_nudge_max_per_session": 5}
    )
    _seed_drift_activity(tmp_path, session_id, drift_calls=3)

    result = run_user_prompt_submit(
        json.dumps({"session_id": session_id, "prompt": "still editing"}),
        project_dir=tmp_path,
        config=cfg,
        client="antigravity",
    )
    assert result.additional_context is not None
    assert "ToolSearch" not in result.additional_context


def test_never_loaded_nudge_stays_claude_only_and_does_not_burn_budget(
    tmp_path: Path,
) -> None:
    """A suppressed 'never loaded' nudge on a non-Claude host must not insert a
    routing_nudge row — otherwise it silently exhausts
    routing_nudge_max_per_session on messages nobody ever sees.
    """
    session_id = "sess-never-loaded-cursor"
    migrate(project_dir=tmp_path, run_integrity_check=False)
    cfg = BrainConfig(injection={"routing_nudge_max_per_session": 1})

    for _ in range(3):
        result = run_user_prompt_submit(
            json.dumps({"session_id": session_id, "prompt": "hi"}),
            project_dir=tmp_path,
            config=cfg,
            client="cursor",
        )
        assert result.additional_context is None

    conn = connect(brain_db_path(tmp_path))
    try:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM session_activity "
            "WHERE session_id = ? AND kind = 'routing_nudge'",
            (session_id,),
        ).fetchone()["c"]
    finally:
        conn.close()
    assert count == 0


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


# --- P3: host-neutral PostToolUse failure detection --------------------------


def _post_tool_failure_cases() -> list[dict]:
    return [
        {"is_error": True},
        {"exit_code": 1},
        {"error": "command not found"},
        {"tool_response": {"error": "ENOENT"}},
    ]


def _post_tool_success_cases() -> list[dict]:
    return [
        {},
        {"exit_code": 0},
        {"error": ""},
        {"is_error": False},
        # Successful commands write to stderr constantly. Treating stderr text
        # as failure would not merely create bogus error neurons — it also
        # suppresses record_file_seed / graph sync / process_post_tool for that
        # call, silently degrading file-seeded recall and procedure learning.
        {"tool_response": {"stdout": "ok", "stderr": "Switched to branch main"}},
        {"tool_response": {"stdout": "done", "stderr": "npm WARN deprecated"}},
        {"tool_response": {"stdout": "", "stderr": "2 passed in 0.4s"}},
    ]


def test_post_tool_infers_failure_from_payload(tmp_path: Path) -> None:
    from brainkm.services.hooks import run_post_tool_use
    from brainkm.services.tool_feedback import get_tool_feedback

    migrate(project_dir=tmp_path, run_integrity_check=False)
    for i, extra in enumerate(_post_tool_failure_cases()):
        payload = {"session_id": f"s-fail-{i}", "tool_name": "Bash", **extra}
        result = run_post_tool_use(json.dumps(payload), project_dir=tmp_path)
        assert result.skipped is False

    conn = connect(brain_db_path(tmp_path))
    try:
        summary = get_tool_feedback(conn, "Bash")
        assert summary is not None
        assert summary.failure_count == len(_post_tool_failure_cases())
        assert summary.success_count == 0
    finally:
        conn.close()


def test_post_tool_success_not_misread_as_failure(tmp_path: Path) -> None:
    from brainkm.services.hooks import run_post_tool_use
    from brainkm.services.tool_feedback import get_tool_feedback

    migrate(project_dir=tmp_path, run_integrity_check=False)
    for i, extra in enumerate(_post_tool_success_cases()):
        payload = {"session_id": f"s-ok-{i}", "tool_name": "Read", **extra}
        run_post_tool_use(json.dumps(payload), project_dir=tmp_path)

    conn = connect(brain_db_path(tmp_path))
    try:
        summary = get_tool_feedback(conn, "Read")
        assert summary is not None
        assert summary.failure_count == 0
        assert summary.success_count == len(_post_tool_success_cases())
    finally:
        conn.close()


def test_detect_tool_failure_can_be_disabled(tmp_path: Path) -> None:
    from brainkm.services.hooks import run_post_tool_use
    from brainkm.services.tool_feedback import get_tool_feedback

    migrate(project_dir=tmp_path, run_integrity_check=False)
    config = BrainConfig()
    config.capture.detect_tool_failure = False
    payload = {"session_id": "s-disabled", "tool_name": "Bash", "exit_code": 1}
    run_post_tool_use(json.dumps(payload), project_dir=tmp_path, config=config)

    conn = connect(brain_db_path(tmp_path))
    try:
        summary = get_tool_feedback(conn, "Bash")
        assert summary is not None
        assert summary.failure_count == 0
        assert summary.success_count == 1
    finally:
        conn.close()


def test_successful_write_with_stderr_still_records_file_seed(tmp_path: Path) -> None:
    """Regression: stderr text on a *successful* Write must not be read as
    failure. failed=True skips record_file_seed / graph sync / procedure
    learning, so a false positive here silently degrades retrieval.
    """
    from brainkm.services.hooks import run_post_tool_use

    migrate(project_dir=tmp_path, run_integrity_check=False)
    payload = {
        "session_id": "s-stderr-write",
        "tool_name": "Write",
        "tool_input": {"file_path": str(tmp_path / "svc.py")},
        "tool_response": {"stdout": "", "stderr": "warning: LF will be replaced by CRLF"},
    }
    run_post_tool_use(json.dumps(payload), project_dir=tmp_path)

    # Assert on the raw file_seed row: load_file_seeds() resolves paths through
    # the code graph and returns node ids, which are empty in a fresh brain.
    conn = connect(brain_db_path(tmp_path))
    try:
        rows = conn.execute(
            "SELECT tool_name FROM session_activity "
            "WHERE session_id = ? AND kind = 'file_seed'",
            ("s-stderr-write",),
        ).fetchall()
    finally:
        conn.close()
    assert rows, "successful Write with stderr must still record a file seed"
    assert rows[0][0].endswith("svc.py")


def test_post_tool_failure_suppresses_graph_sync_and_procedure(tmp_path: Path) -> None:
    """A payload-inferred failure must behave exactly like failed=True — no
    graph sync request, no procedure reinforcement (process_post_tool skip)."""
    from brainkm.services.hooks import run_post_tool_use

    migrate(project_dir=tmp_path, run_integrity_check=False)
    config = BrainConfig()
    payload = {
        "session_id": "s-graph",
        "tool_name": "Write",
        "exit_code": 2,
        "tool_input": {"path": "x.py"},
    }
    result = run_post_tool_use(json.dumps(payload), project_dir=tmp_path, config=config)
    assert result.skipped is False


# --- P8: --client forwarded to PostToolUse -----------------------------------


def test_post_tool_use_client_antigravity_resolves_project_dir_without_sniff_keys(
    tmp_path: Path,
) -> None:
    """A payload with no workspacePaths/conversationId key must still resolve
    the Antigravity project_dir when client="antigravity" is passed explicitly
    — the key-sniff fallback alone would miss this and risk a shadow brain
    under cwd (.agents/) instead of the real project root.
    """
    from brainkm.services.hooks import run_post_tool_use

    migrate(project_dir=tmp_path, run_integrity_check=False)
    payload = {
        "session_id": "s-agy-explicit",
        "tool_name": "write_to_file",
        "tool_input": {"TargetFile": str(tmp_path / "notes.py")},
    }
    result = run_post_tool_use(
        json.dumps(payload),
        project_dir=tmp_path,
        client="antigravity",
    )
    assert result.skipped is False
    # No shadow .agents/.brain directory should have been created under tmp_path.
    assert not (tmp_path / ".agents" / ".brain").exists()


# --- P7: Cursor stop hook -----------------------------------------------------


def test_run_agent_stop_flushes_use_counts_for_cursor(tmp_path: Path) -> None:
    """P7: Cursor's `stop` hook (confirmed via Cursor docs — distinct from
    sessionEnd, fires when the agent loop ends) reaches run_agent_stop just
    like Claude/Antigravity's Stop does.
    """
    from brainkm.services.hooks import run_agent_stop
    from brainkm.services.session_activity import record_mcp_tool_use

    migrate(project_dir=tmp_path, run_integrity_check=False)
    conn = connect(brain_db_path(tmp_path))
    try:
        record_mcp_tool_use(conn, "sess-cursor-stop", "recall", result_count=1)
        conn.commit()
    finally:
        conn.close()

    result = run_agent_stop(
        json.dumps({"session_id": "sess-cursor-stop"}),
        project_dir=tmp_path,
        client="cursor",
    )
    assert result.hook == "Stop"
    assert result.skipped is False
