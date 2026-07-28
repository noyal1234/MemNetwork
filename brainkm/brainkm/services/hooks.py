"""Hook handlers — SessionStart, SessionEnd, PreToolUse, Claude subagent lifecycle."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from brainkm.db.checkpoint import wal_checkpoint
from brainkm.db.connection import connect
from brainkm.db.migrate import migrate
from brainkm.db.paths import brain_db_path
from brainkm.logging_config import get_logger
from brainkm.models.brain_config import BrainConfig
from brainkm.services.audit import utc_now_iso
from brainkm.services.capture import capture_transcript_file
from brainkm.services.config_loader import load_brain_config
from brainkm.services.handover import parse_precompact_hook_payload
from brainkm.services.learning import persist_neuron_hits, process_post_tool
from brainkm.services.memory import new_ulid
from brainkm.services.session_activity import flush_use_counts, record_neuron_activity
from brainkm.services.snapshot import _TOOL_SEARCH_SELECT, build_frozen_snapshot, resolve_session_id

logger = get_logger("services.hooks")

_TOOL_NAME_KEYS = ("tool_name", "toolName", "tool", "name")
_SESSION_ID_KEYS = (
    "session_id",
    "sessionId",
    "conversation_id",
    "conversationId",
    "agent_id",
    "agentId",
    "subagent_id",
    "subagentId",
)

# Internal camelCase → Claude PascalCase hookEventName
_CLAUDE_EVENT_NAMES: dict[str, str] = {
    "sessionStart": "SessionStart",
    "sessionEnd": "SessionEnd",
    "preCompact": "PreCompact",
    "postCompact": "PostCompact",
    "preToolUse": "PreToolUse",
    "postToolUse": "PostToolUse",
    "postToolUseFailure": "PostToolUseFailure",
    "userPromptSubmit": "UserPromptSubmit",
    "subagentStart": "SubagentStart",
    "subagentStop": "SubagentStop",
    "stop": "Stop",
}

# Events that may emit Claude context / permission JSON
_CLAUDE_INJECT_EVENTS = frozenset(
    {"sessionStart", "postCompact", "preToolUse", "subagentStart", "userPromptSubmit"}
)

# Codex uses the same PascalCase hookEventName envelope as Claude for inject events.
_CODEX_INJECT_EVENTS = frozenset({"sessionStart", "userPromptSubmit", "preToolUse", "postCompact"})
# Codex Stop / compact events must emit valid JSON (plain text is invalid for Stop).
_CODEX_CONTINUE_EVENTS = frozenset({"sessionEnd", "stop", "preCompact", "postToolUse"})


@dataclass(frozen=True)
class HookRunResult:
    hook: str
    session_id: str | None
    skipped: bool
    reason: str | None
    additional_context: str | None = None
    snapshot_neuron_ids: tuple[str, ...] = ()


def build_cursor_hook_stdout(result: HookRunResult, event: str) -> dict[str, object]:
    """Build JSON stdout for Cursor command hooks (stdout must be valid JSON)."""
    if event == "preToolUse":
        response: dict[str, object] = {"permission": "allow"}
        if result.additional_context:
            response["agent_message"] = result.additional_context
        return response

    if event in {"sessionStart", "postToolUse", "postCompact"}:
        response: dict[str, object] = {}
        if result.additional_context:
            response["additional_context"] = result.additional_context
        return response

    msg = f"unsupported Cursor hook event for JSON stdout: {event}"
    raise ValueError(msg)


def build_claude_hook_stdout(result: HookRunResult, event: str) -> dict[str, object] | None:
    """Build Claude ``hookSpecificOutput`` JSON, or ``None`` for capture-only (empty stdout).

    Claude Code requires the envelope with ``hookEventName``; bare additionalContext is dropped.
    Capture-only events return ``None`` so the CLI prints nothing (exit 0).
    """
    if event not in _CLAUDE_INJECT_EVENTS:
        return None
    if result.skipped or not result.additional_context:
        # PreToolUse still should not block — silence with allow is fine.
        if event == "preToolUse":
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                }
            }
        return None

    hook_event_name = _CLAUDE_EVENT_NAMES.get(event, event)
    specific: dict[str, object] = {
        "hookEventName": hook_event_name,
        "additionalContext": result.additional_context,
    }
    if event == "preToolUse":
        specific["permissionDecision"] = "allow"
    return {"hookSpecificOutput": specific}


def build_codex_hook_stdout(result: HookRunResult, event: str) -> dict[str, object]:
    """Build Codex CLI hook stdout (always JSON — Stop rejects plain text).

    Inject events use Claude-compatible ``hookSpecificOutput.additionalContext``.
    Capture / continue events return ``{"continue": true}`` and never ``decision: block``.
    """
    if event in _CODEX_INJECT_EVENTS:
        if result.skipped or not result.additional_context:
            if event == "preToolUse":
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "allow",
                    }
                }
            if event == "postCompact":
                return {"continue": True}
            return {"continue": True}

        hook_event_name = _CLAUDE_EVENT_NAMES.get(event, event)
        specific: dict[str, object] = {
            "hookEventName": hook_event_name,
            "additionalContext": result.additional_context,
        }
        # Prefer additionalContext-only for PreToolUse; Codex denies via
        # permissionDecision=deny / exit 2 — we never block from brainkm.
        out: dict[str, object] = {"hookSpecificOutput": specific, "continue": True}
        return out

    if event in _CODEX_CONTINUE_EVENTS or event in _CLAUDE_EVENT_NAMES:
        return {"continue": True}

    return {"continue": True}


def _parse_hook_object(raw: str) -> dict[str, object]:
    data = json.loads(raw)
    if not isinstance(data, dict):
        msg = "hook payload must be a JSON object"
        raise ValueError(msg)
    return data


def _session_id_from_payload(data: dict[str, object]) -> str | None:
    for key in _SESSION_ID_KEYS:
        value = data.get(key)
        if value is not None:
            return str(value)
    return None


def _tool_name_from_payload(data: dict[str, object]) -> str | None:
    for key in _TOOL_NAME_KEYS:
        value = data.get(key)
        if value is not None:
            return str(value)
    tool_call = data.get("toolCall")
    if isinstance(tool_call, dict):
        name = tool_call.get("name")
        if name is not None:
            return str(name)
    return None


def _tool_input_from_payload(data: dict[str, object]) -> dict[str, object]:
    for key in ("tool_input", "toolInput", "input", "arguments"):
        value = data.get(key)
        if isinstance(value, dict):
            return value
    tool_call = data.get("toolCall")
    if isinstance(tool_call, dict):
        args = tool_call.get("args")
        if isinstance(args, dict):
            return args
    return {}


def normalize_antigravity_stdin(
    data: dict[str, object],
    *,
    event: str | None = None,
) -> dict[str, object]:
    """Map Antigravity hook fields onto Cursor/Claude-shaped keys for shared handlers."""
    out = dict(data)
    if event:
        out.setdefault("hook_event_name", event)
        out.setdefault("hookEventName", event)
    conv = data.get("conversationId") or data.get("conversation_id")
    if conv is not None:
        out.setdefault("session_id", str(conv))
        out.setdefault("sessionId", str(conv))
    transcript = data.get("transcriptPath") or data.get("transcript_path")
    if transcript is not None:
        out.setdefault("transcript_path", str(transcript))
        out.setdefault("transcriptPath", str(transcript))
    tool_name = _tool_name_from_payload(data)
    if tool_name:
        out.setdefault("tool_name", tool_name)
        out.setdefault("toolName", tool_name)
    tool_input = _tool_input_from_payload(data)
    if tool_input:
        # Map AGY file/shell args to common observe keys.
        mapped = dict(tool_input)
        filepath = tool_input.get("TargetFile") or tool_input.get("AbsolutePath")
        if isinstance(filepath, str) and filepath.strip() and "path" not in mapped:
            mapped["path"] = filepath
            mapped["file_path"] = filepath
        if "CommandLine" in tool_input and "command" not in mapped:
            mapped["command"] = tool_input["CommandLine"]
        out.setdefault("tool_input", mapped)
        out.setdefault("toolInput", mapped)
    return out


def _pattern_matches_tool(pattern: str, tool_name: str) -> bool:
    normalized_pattern = pattern.strip().lower()
    normalized_tool = tool_name.strip().lower()

    aliases = {
        "write": ("write", "write_to_file"),
        "edit": ("edit", "replace_file_content", "multi_replace_file_content"),
        "run_terminal": (
            "shell",
            "bash",
            "run_terminal",
            "run_terminal_cmd",
            "terminal",
            "run_command",
        ),
        "view": ("view", "view_file", "read_file"),
    }
    candidates = aliases.get(normalized_pattern, (normalized_pattern,))
    return any(candidate in normalized_tool for candidate in candidates)


def build_antigravity_hook_stdout(
    result: HookRunResult,
    event: str,
) -> dict[str, object]:
    """Build Antigravity hook stdout JSON for the given PascalCase or camelCase event."""
    normalized = event[0].lower() + event[1:] if event and event[0].isupper() else event
    # Accept both PreInvocation and preInvocation.
    key = normalized.replace("PreInvocation", "preInvocation").replace(
        "SessionStart", "sessionStart"
    )
    if event in ("PreInvocation", "preInvocation", "SessionStart", "sessionStart"):
        if result.additional_context:
            return {
                "injectSteps": [
                    {"ephemeralMessage": result.additional_context},
                ]
            }
        return {}
    if event in ("PreToolUse", "preToolUse"):
        if result.additional_context:
            return {
                "decision": "allow",
                "injectSteps": [
                    {"ephemeralMessage": result.additional_context},
                ],
            }
        return {"decision": "allow"}
    if event in ("PostToolUse", "postToolUse", "PostInvocation", "postInvocation"):
        return {}
    if event in ("Stop", "stop"):
        return {"decision": "stop"}
    _ = key
    return {}


_CONTEXT_HINT_KEYS = ("context_hint", "contextHint", "hint", "task")


def _context_hint_from_payload(data: dict[str, object]) -> str | None:
    for key in _CONTEXT_HINT_KEYS:
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()[:500]
    return None


def run_session_start(
    raw: str,
    *,
    project_dir: Path | None = None,
    config: BrainConfig | None = None,
) -> HookRunResult:
    """SessionStart — migrate DB, build frozen injection snapshot (not updated mid-session)."""
    cfg = config or load_brain_config(project_dir)
    data = _parse_hook_object(raw) if raw.strip() else {}
    session_id = _session_id_from_payload(data) or resolve_session_id(data)
    context_hint = _context_hint_from_payload(data)

    if not cfg.injection.session_start:
        logger.info("hook=SessionStart session_id=%s skipped=session_start_disabled", session_id)
        return HookRunResult(
            hook="SessionStart",
            session_id=session_id,
            skipped=True,
            reason="injection.session_start disabled",
        )

    migrate(project_dir=project_dir, run_integrity_check=True)

    conn = connect(brain_db_path(project_dir))
    try:
        from brainkm.services.compression.cohort import assign_session_cohort

        assign_session_cohort(conn, session_id, cfg.compression)
        snapshot = build_frozen_snapshot(
            conn,
            session_id,
            cfg,
            context_hint=context_hint,
        )
        record_neuron_activity(
            conn,
            session_id,
            list(snapshot.neuron_ids),
            source="session_start",
        )
        conn.commit()
    finally:
        conn.close()

    logger.info(
        "hook=SessionStart session_id=%s migrated=1 snapshot_neurons=%d",
        session_id,
        len(snapshot.neuron_ids),
    )
    return HookRunResult(
        hook="SessionStart",
        session_id=session_id,
        skipped=False,
        reason=None,
        additional_context=snapshot.pack_text if cfg.injection.frozen_snapshot else None,
        snapshot_neuron_ids=snapshot.neuron_ids,
    )


def run_session_end(
    raw: str,
    *,
    project_dir: Path | None = None,
    config: BrainConfig | None = None,
) -> HookRunResult:
    """SessionEnd — capture transcript into neurons + chunk_sources.

    Codex maps Stop → this handler (no SessionEnd). When ``stop_hook_active`` is
    true the turn was already continued by a prior Stop hook — skip re-capture.
    """
    from brainkm.config import apply_project_env

    apply_project_env(project_dir)
    cfg = config or load_brain_config(project_dir)
    cwd = project_dir if project_dir is not None else Path.cwd()

    if not cfg.capture.transcripts:
        return HookRunResult(
            hook="SessionEnd",
            session_id=None,
            skipped=True,
            reason="capture.transcripts disabled",
        )

    # Guard Codex Stop re-entry before parsing the transcript path.
    if raw.strip():
        try:
            preview = _parse_hook_object(raw)
        except (json.JSONDecodeError, ValueError):
            preview = {}
        if bool(preview.get("stop_hook_active") or preview.get("stopHookActive")):
            session_id = _session_id_from_payload(preview)
            logger.info(
                "hook=SessionEnd session_id=%s skipped=stop_hook_active",
                session_id,
            )
            return HookRunResult(
                hook="SessionEnd",
                session_id=session_id,
                skipped=True,
                reason="stop_hook_active",
            )

    payload = parse_precompact_hook_payload(raw, cwd=cwd)
    session_id = payload.session_id or payload.conversation_id

    logger.info(
        "hook=SessionEnd session_id=%s transcript=%s",
        session_id,
        payload.transcript_path.name,
    )

    distill_timeout = max(
        cfg.handover.precompact_distill_timeout_seconds,
        min(90, int(cfg.handover.precompact_distill_timeout_seconds * 4) or 20),
    )
    result = capture_transcript_file(
        payload.transcript_path,
        project_dir=project_dir,
        config=cfg,
        session_id=session_id,
        distill_timeout_seconds=distill_timeout,
    )

    conn = connect(brain_db_path(project_dir))
    try:
        if cfg.capture.auto_observe and result.session_id:
            from brainkm.services.observe import promote_session_observations

            promo = promote_session_observations(
                conn,
                session_id=result.session_id,
                config=cfg,
                project_dir=project_dir,
            )
            logger.info(
                "hook=SessionEnd session_id=%s observe_promoted=%d archived=%d",
                result.session_id,
                promo.promoted,
                promo.archived,
            )
        flushed = flush_use_counts(conn, result.session_id)
        from brainkm.services.session_activity import clear_file_seeds

        clear_file_seeds(conn, result.session_id)
        from brainkm.services.feedback import mark_ignored_since_injection
        from brainkm.services.learning import (
            decay_co_activation_edges,
            delete_session_learning_state,
        )

        mark_ignored_since_injection(conn, session_id=result.session_id)
        # DROP unconsumed pairwise episode — no PostTool evidence ⇒ no reinforcement.
        delete_session_learning_state(conn, result.session_id)
        if cfg.decay.enabled and cfg.decay.consolidate_on_session_end:
            decay_co_activation_edges(
                conn,
                idle_days=cfg.learning.co_activation_idle_days,
                decay_factor=cfg.learning.co_activation_decay_factor,
                min_weight=cfg.learning.co_activation_min_weight,
                dry_run=False,
            )
        from brainkm.services.lifecycle import archive_expired_observations

        archive_expired_observations(conn, config=cfg, dry_run=False)
        wal_checkpoint(conn)
        conn.commit()
        if flushed:
            logger.info(
                "hook=SessionEnd session_id=%s use_count_flushed=%d",
                result.session_id,
                flushed,
            )
    finally:
        conn.close()

    if result.skipped:
        return HookRunResult(
            hook="SessionEnd",
            session_id=result.session_id,
            skipped=True,
            reason=result.reason,
        )

    graph_warning: str | None = None
    if cfg.graphify.enabled:
        from brainkm.services.graphify_sync import maybe_import_stale_graph_on_session_end

        graph_warning = maybe_import_stale_graph_on_session_end(project_dir=project_dir, config=cfg)
        if graph_warning:
            logger.warning("hook=SessionEnd graph_fallback=%s", graph_warning)

    return HookRunResult(
        hook="SessionEnd",
        session_id=result.session_id,
        skipped=False,
        reason=graph_warning,
    )


def run_pre_tool_use(
    raw: str,
    *,
    project_dir: Path | None = None,
    config: BrainConfig | None = None,
) -> HookRunResult:
    """PreToolUse — match configured tools and inject a bounded context_pack when seeded."""
    data = _parse_hook_object(raw)
    # AGY payloads include workspacePaths; resolve before loading BrainConfig.
    if data.get("workspacePaths") or data.get("workspace_paths") or data.get("conversationId"):
        from brainkm.services.antigravity_session import resolve_antigravity_project_dir

        data = normalize_antigravity_stdin(data, event="PreToolUse")
        project_dir = resolve_antigravity_project_dir(data, explicit=project_dir)
    cfg = config or load_brain_config(project_dir)
    tool_name = _tool_name_from_payload(data)
    session_id = _session_id_from_payload(data)

    if not cfg.injection.pre_tool_patterns:
        return HookRunResult(
            hook="PreToolUse",
            session_id=session_id,
            skipped=True,
            reason="no pre_tool patterns configured",
        )

    if tool_name is None:
        return HookRunResult(
            hook="PreToolUse",
            session_id=session_id,
            skipped=True,
            reason="missing tool name in hook payload",
        )

    matched = any(
        _pattern_matches_tool(pattern, tool_name) for pattern in cfg.injection.pre_tool_patterns
    )
    if not matched:
        return HookRunResult(
            hook="PreToolUse",
            session_id=session_id,
            skipped=True,
            reason="tool not matched",
        )

    migrate(project_dir=project_dir, run_integrity_check=False)
    conn = connect(brain_db_path(project_dir))
    try:
        from brainkm.services.context_pack import compile_pre_tool_pack

        pack = compile_pre_tool_pack(conn, data, config=cfg, project_dir=project_dir)
        if pack is not None:
            persist_neuron_hits(
                conn,
                session_id,
                [node.node_id for node in pack.neurons],
                source="pre_tool",
                cap=cfg.learning.session_window_size,
            )
            conn.commit()
    finally:
        conn.close()

    if pack is None:
        logger.info(
            "hook=PreToolUse session_id=%s tool=%s context_pack=skipped no_seed",
            session_id,
            tool_name,
        )
        return HookRunResult(
            hook="PreToolUse",
            session_id=session_id,
            skipped=True,
            reason="no meaningful pre-tool seed",
        )

    logger.info(
        "hook=PreToolUse session_id=%s tool=%s context_pack=tokens=%d",
        session_id,
        tool_name,
        pack.truncation.tokens_used,
    )
    return HookRunResult(
        hook="PreToolUse",
        session_id=session_id,
        skipped=False,
        reason=None,
        additional_context=pack.pack_text,
    )


def run_post_compact(
    raw: str,
    *,
    project_dir: Path | None = None,
    config: BrainConfig | None = None,
) -> HookRunResult:
    """PostCompact — refresh frozen injection snapshot after compaction."""
    cfg = config or load_brain_config(project_dir)
    data = _parse_hook_object(raw) if raw.strip() else {}
    session_id = _session_id_from_payload(data) or resolve_session_id(data)
    context_hint = _context_hint_from_payload(data)

    migrate(project_dir=project_dir, run_integrity_check=False)
    conn = connect(brain_db_path(project_dir))
    try:
        snapshot = build_frozen_snapshot(
            conn,
            session_id,
            cfg,
            force=True,
            context_hint=context_hint,
        )
        record_neuron_activity(
            conn,
            session_id,
            list(snapshot.neuron_ids),
            source="post_compact",
        )
        conn.commit()
    finally:
        conn.close()

    logger.info(
        "hook=PostCompact session_id=%s snapshot_refreshed neurons=%d",
        session_id,
        len(snapshot.neuron_ids),
    )
    return HookRunResult(
        hook="PostCompact",
        session_id=session_id,
        skipped=False,
        reason=None,
        additional_context=snapshot.pack_text if cfg.injection.frozen_snapshot else None,
        snapshot_neuron_ids=snapshot.neuron_ids,
    )


def run_post_tool_use(
    raw: str,
    *,
    project_dir: Path | None = None,
    config: BrainConfig | None = None,
    failed: bool = False,
) -> HookRunResult:
    """PostToolUse — observations, graph sync, co-activation / procedure promotion."""
    data = _parse_hook_object(raw)
    if data.get("workspacePaths") or data.get("workspace_paths") or data.get("conversationId"):
        from brainkm.services.antigravity_session import resolve_antigravity_project_dir

        data = normalize_antigravity_stdin(data, event="PostToolUse")
        project_dir = resolve_antigravity_project_dir(data, explicit=project_dir)
    cfg = config or load_brain_config(project_dir)
    session_id = _session_id_from_payload(data)
    tool_name = _tool_name_from_payload(data) or ""

    if (
        cfg.graphify.enabled
        and cfg.graphify.auto_sync.enabled
        and cfg.graphify.auto_sync.trigger_on_post_tool
        and tool_name
        and not failed
    ):
        matched = any(_pattern_matches_tool(pattern, tool_name) for pattern in ("write", "edit"))
        if matched:
            from brainkm.services.graphify_sync import request_graph_sync

            request_graph_sync(project_dir)
            logger.debug(
                "hook=PostToolUse session_id=%s tool=%s graph_sync_requested=1",
                session_id,
                tool_name,
            )

    if tool_name or cfg.capture.auto_observe:
        conn = connect(brain_db_path(project_dir))
        try:
            if (
                tool_name
                and not failed
                and any(_pattern_matches_tool(p, tool_name) for p in ("write", "edit"))
            ):
                from brainkm.services.observe import extract_observation_path
                from brainkm.services.session_activity import record_file_seed

                path = extract_observation_path(data)
                if path and session_id:
                    record_file_seed(conn, session_id, path)
            if cfg.capture.auto_observe and tool_name:
                from brainkm.services.observe import record_observation

                obs = record_observation(
                    conn,
                    session_id=session_id,
                    tool_name=tool_name,
                    payload=data,
                    config=cfg,
                    failed=failed,
                )
                if obs.stored:
                    logger.debug(
                        "hook=PostToolUse observe_stored node_id=%s failed=%s",
                        obs.node_id,
                        failed,
                    )
            if tool_name and not failed:
                process_post_tool(
                    conn,
                    session_id,
                    tool_name,
                    data,
                    config=cfg,
                )
            conn.commit()
        except Exception as exc:  # pragma: no cover - defensive hook fallback
            logger.warning("hook=PostToolUse learning_error=%s", exc)
        finally:
            conn.close()

    return HookRunResult(
        hook="PostToolUseFailure" if failed else "PostToolUse",
        session_id=session_id,
        skipped=False,
        reason=None,
    )


def _maybe_routing_nudge(
    conn: sqlite3.Connection,
    session_id: str | None,
    cfg: BrainConfig,
) -> str | None:
    """Short, self-disabling reminder to use brainkm MCP tools for this session.

    Suppressed once the session has any real brainkm MCP call (source in
    mcp/mcp_abstained), and capped so a session that never adopts the tools
    isn't nagged forever.
    """
    if not cfg.injection.routing_nudge or not session_id:
        return None
    already_used = conn.execute(
        """
        SELECT 1 FROM session_activity
        WHERE session_id = ? AND source IN ('mcp', 'mcp_abstained')
        LIMIT 1
        """,
        (session_id,),
    ).fetchone()
    if already_used is not None:
        return None
    nudge_count = conn.execute(
        "SELECT COUNT(*) AS c FROM session_activity WHERE session_id = ? AND kind = 'routing_nudge'",
        (session_id,),
    ).fetchone()["c"]
    if nudge_count >= cfg.injection.routing_nudge_max_per_session:
        return None
    conn.execute(
        """
        INSERT INTO session_activity (id, session_id, kind, node_id, tool_name, source, created_at)
        VALUES (?, ?, 'routing_nudge', NULL, NULL, 'hook', ?)
        """,
        (new_ulid(), session_id, utc_now_iso()),
    )
    return (
        "brainkm reminder: recall/traverse/context_pack/brain_stats/remember/trace_changes "
        f'may be deferred — run ToolSearch "{_TOOL_SEARCH_SELECT}" before your first call '
        f'this session, and pass session_id="{session_id}" on every brainkm call.'
    )


def run_user_prompt_submit(
    raw: str,
    *,
    project_dir: Path | None = None,
    config: BrainConfig | None = None,
) -> HookRunResult:
    """UserPromptSubmit — routing nudge, then store a capped prompt gist when auto_observe is on."""
    cfg = config or load_brain_config(project_dir)
    data = _parse_hook_object(raw)
    session_id = _session_id_from_payload(data)

    conn = connect(brain_db_path(project_dir))
    try:
        nudge = _maybe_routing_nudge(conn, session_id, cfg)
        conn.commit()

        if not cfg.capture.auto_observe:
            return HookRunResult(
                hook="UserPromptSubmit",
                session_id=session_id,
                skipped=nudge is None,
                reason="auto_observe disabled",
                additional_context=nudge,
            )
        prompt = ""
        for key in ("prompt", "user_prompt", "message", "text"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                prompt = value
                break
        if not prompt:
            return HookRunResult(
                hook="UserPromptSubmit",
                session_id=session_id,
                skipped=nudge is None,
                reason="missing prompt",
                additional_context=nudge,
            )

        from brainkm.services.observe import record_prompt_observation

        obs = record_prompt_observation(
            conn,
            session_id=session_id,
            prompt=prompt,
            config=cfg,
        )
        conn.commit()
    finally:
        conn.close()
    return HookRunResult(
        hook="UserPromptSubmit",
        session_id=session_id,
        skipped=not obs.stored and nudge is None,
        reason=obs.skipped_reason,
        additional_context=nudge,
    )


def run_subagent_start(
    raw: str,
    *,
    project_dir: Path | None = None,
    config: BrainConfig | None = None,
) -> HookRunResult:
    """SubagentStart — inject frozen pack and register activity for Claude subagents."""
    cfg = config or load_brain_config(project_dir)
    data = _parse_hook_object(raw) if raw.strip() else {}
    session_id = _session_id_from_payload(data) or resolve_session_id(data)
    context_hint = _context_hint_from_payload(data)

    if not cfg.injection.session_start or not cfg.injection.frozen_snapshot:
        return HookRunResult(
            hook="SubagentStart",
            session_id=session_id,
            skipped=True,
            reason="injection disabled",
        )

    migrate(project_dir=project_dir, run_integrity_check=False)
    conn = connect(brain_db_path(project_dir))
    try:
        snapshot = build_frozen_snapshot(
            conn,
            session_id,
            cfg,
            context_hint=context_hint,
        )
        record_neuron_activity(
            conn,
            session_id,
            list(snapshot.neuron_ids),
            source="subagent_start",
        )
        conn.commit()
    finally:
        conn.close()

    logger.info(
        "hook=SubagentStart session_id=%s snapshot_neurons=%d",
        session_id,
        len(snapshot.neuron_ids),
    )
    return HookRunResult(
        hook="SubagentStart",
        session_id=session_id,
        skipped=False,
        reason=None,
        additional_context=snapshot.pack_text if cfg.injection.frozen_snapshot else None,
        snapshot_neuron_ids=snapshot.neuron_ids,
    )


def run_subagent_stop(
    raw: str,
    *,
    project_dir: Path | None = None,
    config: BrainConfig | None = None,
) -> HookRunResult:
    """SubagentStop — promote observations and flush use counts for the subagent session."""
    cfg = config or load_brain_config(project_dir)
    data = _parse_hook_object(raw) if raw.strip() else {}
    session_id = _session_id_from_payload(data)
    if not session_id:
        return HookRunResult(
            hook="SubagentStop",
            session_id=None,
            skipped=True,
            reason="missing session id",
        )

    conn = connect(brain_db_path(project_dir))
    try:
        promoted = 0
        if cfg.capture.auto_observe:
            from brainkm.services.observe import promote_session_observations

            promo = promote_session_observations(
                conn,
                session_id=session_id,
                config=cfg,
                project_dir=project_dir,
            )
            promoted = promo.promoted
        flushed = flush_use_counts(conn, session_id)
        conn.commit()
    finally:
        conn.close()

    logger.info(
        "hook=SubagentStop session_id=%s promoted=%d flushed=%d",
        session_id,
        promoted,
        flushed,
    )
    return HookRunResult(
        hook="SubagentStop",
        session_id=session_id,
        skipped=False,
        reason=None,
    )


def run_agent_stop(
    raw: str,
    *,
    project_dir: Path | None = None,
    config: BrainConfig | None = None,
    client: str = "cursor",
) -> HookRunResult:
    """Stop — flush use counts; Antigravity idle Stop also distills/handover with debounce."""
    data = _parse_hook_object(raw) if raw.strip() else {}
    kind = (client or "cursor").strip().lower()
    if kind == "antigravity":
        data = normalize_antigravity_stdin(data, event="Stop")
        from brainkm.services.antigravity_session import resolve_antigravity_project_dir

        project_dir = resolve_antigravity_project_dir(data, explicit=project_dir)
    from brainkm.config import apply_project_env

    apply_project_env(project_dir)
    cfg = config or load_brain_config(project_dir)
    session_id = _session_id_from_payload(data)

    if kind == "antigravity" and session_id:
        return _run_antigravity_stop(
            data, session_id=session_id, project_dir=project_dir, config=cfg
        )

    conn = connect(brain_db_path(project_dir))
    try:
        if cfg.capture.auto_observe and session_id:
            gist = ""
            for key in ("last_assistant_message", "stop_reason", "reason"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    gist = value.strip()[:400]
                    break
            if gist:
                from brainkm.services.observe import record_prompt_observation

                record_prompt_observation(
                    conn,
                    session_id=session_id,
                    prompt=f"[stop] {gist}",
                    config=cfg,
                )
        flushed = flush_use_counts(conn, session_id) if session_id else 0
        conn.commit()
    finally:
        conn.close()

    logger.info("hook=Stop session_id=%s flushed=%d", session_id, flushed)
    return HookRunResult(
        hook="Stop",
        session_id=session_id,
        skipped=False,
        reason=None,
    )


def _run_antigravity_stop(
    data: dict[str, object],
    *,
    session_id: str,
    project_dir: Path | None,
    config: BrainConfig,
) -> HookRunResult:
    import time

    from brainkm.services.antigravity_session import (
        get_agy_session,
        parse_antigravity_stop_gates,
        save_agy_session,
        should_run_distill,
    )
    from brainkm.services.handover import run_handover
    from brainkm.services.observe import promote_session_observations

    fully_idle, force = parse_antigravity_stop_gates(data)
    state = get_agy_session(project_dir, session_id)

    conn = connect(brain_db_path(project_dir))
    try:
        if config.capture.auto_observe:
            promo = promote_session_observations(
                conn,
                session_id=session_id,
                config=config,
                project_dir=project_dir,
            )
            logger.info(
                "hook=Stop(agy) session_id=%s observe_promoted=%d project=%s",
                session_id,
                promo.promoted,
                project_dir,
            )
        flushed = flush_use_counts(conn, session_id)
        conn.commit()
    finally:
        conn.close()

    do_distill = should_run_distill(state, fully_idle=fully_idle, force=force)
    if do_distill:
        from brainkm.services.antigravity_session import resolve_all_antigravity_transcripts

        tpaths = resolve_all_antigravity_transcripts(data)
        if tpaths:
            for tpath in tpaths:
                try:
                    run_handover(
                        tpath,
                        project_dir=project_dir,
                        config=config,
                        session_id=session_id,
                    )
                except Exception:  # noqa: BLE001
                    logger.warning("Antigravity Stop handover failed for %s", tpath, exc_info=True)
            primary_path = tpaths[0]
            state.last_distill_at = time.time()
            try:
                state.transcript_byte_offset = primary_path.stat().st_size
                state.last_handover_transcript_bytes = state.transcript_byte_offset
                state.last_handover_at = state.last_distill_at
            except OSError:
                pass
            save_agy_session(project_dir, state)
        else:
            logger.warning(
                "hook=Stop(agy) session_id=%s distill skipped: no transcript path",
                session_id,
            )

    logger.info(
        "hook=Stop(agy) session_id=%s fully_idle=%s distill=%s flushed=%d project=%s",
        session_id,
        fully_idle,
        do_distill,
        flushed,
        project_dir,
    )
    return HookRunResult(
        hook="Stop",
        session_id=session_id,
        skipped=not do_distill and not fully_idle,
        reason=None if do_distill or fully_idle else "not fully idle",
    )


def run_pre_invocation(
    raw: str,
    *,
    project_dir: Path | None = None,
    config: BrainConfig | None = None,
    event: str = "PreInvocation",
) -> HookRunResult:
    """Antigravity PreInvocation / SessionStart — inject throttled pack + synthetic precompact."""
    import hashlib
    import time

    from brainkm.services.antigravity_session import (
        get_agy_session,
        resolve_antigravity_project_dir,
        resolve_antigravity_transcript,
        save_agy_session,
        should_inject_pack,
        should_synthetic_handover,
    )
    from brainkm.services.handover import run_handover

    data = _parse_hook_object(raw) if raw.strip() else {}
    data = normalize_antigravity_stdin(data, event=event)
    project_dir = resolve_antigravity_project_dir(data, explicit=project_dir)
    # Self-heal on every AGY session start: fix hooks + remove shadow brains.
    from brainkm.services.antigravity_session import heal_antigravity_wiring

    heal = heal_antigravity_wiring(project_dir, rewrite_hooks=True)
    if heal.changed:
        logger.info(
            "hook=PreInvocation agy_heal hooks_rewritten=%s shadow_removed=%s sessions_merged=%d",
            heal.hooks_rewritten,
            heal.shadow_removed,
            heal.sessions_merged,
        )
    from brainkm.config import apply_project_env

    apply_project_env(project_dir)
    cfg = config or load_brain_config(project_dir)
    session_id = _session_id_from_payload(data) or resolve_session_id(data)
    invocation_num = int(data.get("invocationNum") or data.get("invocation_num") or 0)
    steps = int(data.get("initialNumSteps") or data.get("initial_num_steps") or 0)
    context_hint = _context_hint_from_payload(data)

    if not cfg.injection.session_start:
        return HookRunResult(
            hook="PreInvocation",
            session_id=session_id,
            skipped=True,
            reason="injection.session_start disabled",
        )

    migrate(project_dir=project_dir, run_integrity_check=invocation_num == 0)
    state = get_agy_session(project_dir, session_id or "unknown")

    transcript_bytes = 0
    tpath = resolve_antigravity_transcript(data)
    if tpath is not None:
        try:
            transcript_bytes = tpath.stat().st_size
        except OSError:
            transcript_bytes = 0

    did_handover = False
    if (
        tpath is not None
        and tpath.is_file()
        and should_synthetic_handover(state, transcript_bytes=transcript_bytes, steps=steps)
    ):
        try:
            run_handover(
                tpath,
                project_dir=project_dir,
                config=cfg,
                session_id=session_id,
            )
            state.last_handover_at = time.time()
            state.last_handover_transcript_bytes = transcript_bytes
            save_agy_session(project_dir, state)
            did_handover = True
            logger.info(
                "hook=PreInvocation synthetic_handover session_id=%s bytes=%d steps=%d",
                session_id,
                transcript_bytes,
                steps,
            )
        except Exception:  # noqa: BLE001
            logger.warning("synthetic precompact handover failed", exc_info=True)

    conn = connect(brain_db_path(project_dir))
    try:
        snapshot = build_frozen_snapshot(
            conn,
            session_id,
            cfg,
            force=did_handover,
            context_hint=context_hint,
        )
        pack_text = snapshot.pack_text if cfg.injection.frozen_snapshot else None
        pack_hash = hashlib.sha256(pack_text.encode("utf-8")).hexdigest()[:16] if pack_text else ""
        inject = should_inject_pack(
            state,
            invocation_num=invocation_num,
            pack_hash=pack_hash,
        )
        if inject and pack_text:
            record_neuron_activity(
                conn,
                session_id,
                list(snapshot.neuron_ids),
                source="pre_invocation",
            )
            conn.commit()
            state.last_inject_invocation = invocation_num
            state.last_inject_pack_hash = pack_hash
            state.bootstrap_done = True
            save_agy_session(project_dir, state)
        else:
            pack_text = None
    finally:
        conn.close()

    logger.info(
        "hook=PreInvocation session_id=%s invocation=%d inject=%s",
        session_id,
        invocation_num,
        bool(pack_text),
    )
    return HookRunResult(
        hook="PreInvocation",
        session_id=session_id,
        skipped=not bool(pack_text),
        reason=None if pack_text else "throttled",
        additional_context=pack_text,
        snapshot_neuron_ids=snapshot.neuron_ids if pack_text else (),
    )


def pre_tool_matcher(patterns: list[str]) -> str:
    """Build a Cursor/Claude preToolUse matcher regex from BrainConfig patterns."""
    mapping = {
        "write": "Write",
        "edit": "Edit",
        "run_terminal": "Shell",
    }
    parts = [mapping.get(pattern, pattern) for pattern in patterns]
    return "|".join(re.escape(part) for part in parts)
