"""Cursor hook handlers — SessionStart, SessionEnd, PreToolUse."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from brainkm.db.checkpoint import wal_checkpoint
from brainkm.db.connection import connect
from brainkm.db.migrate import migrate
from brainkm.db.paths import brain_db_path
from brainkm.logging_config import get_logger
from brainkm.models.brain_config import BrainConfig
from brainkm.services.capture import capture_transcript_file
from brainkm.services.config_loader import load_brain_config
from brainkm.services.handover import parse_precompact_hook_payload
from brainkm.services.learning import persist_neuron_hits, process_post_tool
from brainkm.services.session_activity import flush_use_counts, record_neuron_activity
from brainkm.services.snapshot import build_frozen_snapshot, resolve_session_id

logger = get_logger("services.hooks")

_TOOL_NAME_KEYS = ("tool_name", "toolName", "tool", "name")
_SESSION_ID_KEYS = ("session_id", "sessionId", "conversation_id", "conversationId")


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
    return None


def _pattern_matches_tool(pattern: str, tool_name: str) -> bool:
    normalized_pattern = pattern.strip().lower()
    normalized_tool = tool_name.strip().lower()

    aliases = {
        "write": ("write",),
        "edit": ("edit",),
        "run_terminal": ("shell", "run_terminal", "run_terminal_cmd", "terminal"),
    }
    candidates = aliases.get(normalized_pattern, (normalized_pattern,))
    return any(candidate in normalized_tool for candidate in candidates)


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
    """SessionEnd — capture transcript into neurons + chunk_sources."""
    cfg = config or load_brain_config(project_dir)
    cwd = project_dir if project_dir is not None else Path.cwd()

    if not cfg.capture.transcripts:
        return HookRunResult(
            hook="SessionEnd",
            session_id=None,
            skipped=True,
            reason="capture.transcripts disabled",
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
    cfg = config or load_brain_config(project_dir)
    data = _parse_hook_object(raw)
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
        _pattern_matches_tool(pattern, tool_name)
        for pattern in cfg.injection.pre_tool_patterns
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
    """PostCompact — refresh frozen injection snapshot after Cursor compaction."""
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
    cfg = config or load_brain_config(project_dir)
    data = _parse_hook_object(raw)
    session_id = _session_id_from_payload(data)
    tool_name = _tool_name_from_payload(data) or ""

    if (
        cfg.graphify.enabled
        and cfg.graphify.auto_sync.enabled
        and cfg.graphify.auto_sync.trigger_on_post_tool
        and tool_name
        and not failed
    ):
        matched = any(
            _pattern_matches_tool(pattern, tool_name)
            for pattern in ("write", "edit")
        )
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


def run_user_prompt_submit(
    raw: str,
    *,
    project_dir: Path | None = None,
    config: BrainConfig | None = None,
) -> HookRunResult:
    """UserPromptSubmit — store a capped prompt gist when auto_observe is on."""
    cfg = config or load_brain_config(project_dir)
    data = _parse_hook_object(raw)
    session_id = _session_id_from_payload(data)
    if not cfg.capture.auto_observe:
        return HookRunResult(
            hook="UserPromptSubmit",
            session_id=session_id,
            skipped=True,
            reason="auto_observe disabled",
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
            skipped=True,
            reason="missing prompt",
        )
    conn = connect(brain_db_path(project_dir))
    try:
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
        skipped=not obs.stored,
        reason=obs.skipped_reason,
    )


def pre_tool_matcher(patterns: list[str]) -> str:
    """Build a Cursor preToolUse matcher regex from BrainConfig patterns."""
    mapping = {
        "write": "Write",
        "edit": "Edit",
        "run_terminal": "Shell",
    }
    parts = [mapping.get(pattern, pattern) for pattern in patterns]
    return "|".join(re.escape(part) for part in parts)
