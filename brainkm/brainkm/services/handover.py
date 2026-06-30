"""PreCompact handover — distill transcript, checkpoint WAL, confirm writes."""

from __future__ import annotations

import json
import re
from pathlib import Path

from brainkm.adapters.redaction import RedactionBlockedError
from brainkm.adapters.transcript_v1 import parse_transcript_file
from brainkm.db.checkpoint import confirm_writes, wal_checkpoint
from brainkm.db.connection import connect
from brainkm.db.migrate import migrate
from brainkm.db.paths import brain_db_path, brain_dir
from brainkm.logging_config import get_logger
from brainkm.models.brain_config import BrainConfig
from brainkm.models.distill import DistilledNeuron, ParsedTranscript
from brainkm.models.handover import HandoverResult, PreCompactHookPayload
from brainkm.services.capture import capture_transcript_file
from brainkm.services.chunks import link_chunk_sources
from brainkm.services.config_loader import load_brain_config
from brainkm.services.memory import create_neuron, new_ulid

logger = get_logger("services.handover")

HANDOVER_SUBTYPES = frozenset({"decision", "context", "rule", "error"})
_TITLE_MAX = 120


def parse_precompact_hook_payload(
    raw: str,
    *,
    cwd: Path | None = None,
) -> PreCompactHookPayload:
    """Parse Cursor PreCompact hook stdin JSON."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        msg = "hook payload must be a JSON object"
        raise ValueError(msg)

    path_value = (
        data.get("transcript_path")
        or data.get("transcriptPath")
        or data.get("transcript")
    )
    if not path_value:
        msg = "hook payload missing transcript_path"
        raise ValueError(msg)

    transcript_path = Path(str(path_value))
    if not transcript_path.is_absolute() and cwd is not None:
        transcript_path = cwd / transcript_path

    session_id = data.get("session_id") or data.get("sessionId")
    conversation_id = data.get("conversation_id") or data.get("conversationId")
    if session_id is not None:
        session_id = str(session_id)
    if conversation_id is not None:
        conversation_id = str(conversation_id)

    return PreCompactHookPayload(
        transcript_path=transcript_path,
        session_id=session_id,
        conversation_id=conversation_id,
    )


def _title_from_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= _TITLE_MAX:
        return cleaned
    return cleaned[: _TITLE_MAX - 3].rstrip() + "..."


def _context_neuron(parsed: ParsedTranscript, *, chunk_ids: list[str]) -> DistilledNeuron | None:
    """Capture the latest user turn as session context for post-compact recall."""
    for message in reversed(parsed.messages):
        if message.role != "user":
            continue
        text = message.text.strip()
        if len(text) < 20:
            continue
        neuron = DistilledNeuron(
            subtype="context",
            title=_title_from_text(text),
            body=text,
            tags=["handover", "context"],
            chunk_ids=list(chunk_ids),
        )
        if neuron.is_atomic():
            return neuron
    return None


def _latest_user_chunk_ids(conn, session_id: str) -> list[str]:
    row = conn.execute(
        """
        SELECT id FROM session_chunks
        WHERE session_id = ? AND role = 'user'
        ORDER BY ts DESC
        LIMIT 1
        """,
        (session_id,),
    ).fetchone()
    return [str(row[0])] if row else []


def _write_handover_export(
    *,
    project_dir: Path | None,
    session_id: str,
    neurons: list[tuple[str, str, str]],
) -> Path | None:
    if not neurons:
        return None

    root = project_dir if project_dir is not None else Path.cwd()
    export_dir = brain_dir(project_dir) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    export_path = export_dir / f"HANDOVER-{new_ulid()}.md"

    lines = [
        f"# Handover — {session_id}",
        "",
        f"Exported {len(neurons)} neuron(s) before compaction.",
        "",
    ]
    for subtype, title, body in neurons:
        lines.extend([f"## {subtype}: {title}", "", body, ""])

    export_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote handover export path=%s", export_path.relative_to(root))
    return export_path


def _maybe_add_context_neuron(
    conn,
    *,
    transcript_path: Path,
    session_id: str,
) -> int:
    parsed = parse_transcript_file(transcript_path, session_id=session_id)
    chunk_ids = _latest_user_chunk_ids(conn, parsed.session_id)
    context = _context_neuron(parsed, chunk_ids=chunk_ids)
    if context is None:
        return 0

    try:
        record = create_neuron(
            conn,
            title=context.title,
            content=context.body,
            kind="memory",
            subtype="context",
            tags=context.tags,
            source="handover:context",
            session_id=parsed.session_id,
            node_id=new_ulid(),
        )
    except RedactionBlockedError as exc:
        logger.warning("Skipped context neuron blocked by redaction: %s", exc)
        return 0

    if chunk_ids:
        link_chunk_sources(conn, chunk_ids=chunk_ids, neuron_id=record.id)
    return 1


def run_handover(
    transcript_path: Path,
    *,
    project_dir: Path | None = None,
    config: BrainConfig | None = None,
    session_id: str | None = None,
    db_path: Path | None = None,
) -> HandoverResult:
    """Distill transcript for PreCompact, checkpoint WAL, and optionally export markdown."""
    cfg = config or load_brain_config(project_dir)
    resolved_session = session_id or transcript_path.stem

    if not cfg.handover.precompact_enabled:
        logger.info("handover.precompact_enabled=false; skipping")
        return HandoverResult(
            session_id=resolved_session,
            skipped=True,
            reason="precompact disabled",
            chunk_count=0,
            neuron_count=0,
            distill_mode=cfg.capture.distill_mode,
            export_path=None,
            checkpoint_ok=True,
        )

    if not cfg.capture.transcripts:
        return HandoverResult(
            session_id=resolved_session,
            skipped=True,
            reason="capture.transcripts disabled",
            chunk_count=0,
            neuron_count=0,
            distill_mode=cfg.capture.distill_mode,
            export_path=None,
            checkpoint_ok=True,
        )

    if not transcript_path.is_file():
        msg = f"transcript not found: {transcript_path}"
        raise FileNotFoundError(msg)

    logger.info(
        "hook=PreCompact session_id=%s transcript=%s",
        resolved_session,
        transcript_path.name,
    )

    resolved_db = db_path if db_path is not None else brain_db_path(project_dir)
    migrate(db_path=resolved_db, run_integrity_check=False)

    capture_result = capture_transcript_file(
        transcript_path,
        project_dir=project_dir,
        config=cfg,
        session_id=resolved_session,
        db_path=resolved_db,
        skip_duplicate=False,
        distill_timeout_seconds=cfg.handover.precompact_distill_timeout_seconds,
        allowed_subtypes=HANDOVER_SUBTYPES,
    )

    if capture_result.skipped:
        conn = connect(resolved_db)
        try:
            checkpoint = wal_checkpoint(conn)
        finally:
            conn.close()
        return HandoverResult(
            session_id=capture_result.session_id,
            skipped=True,
            reason=capture_result.reason,
            chunk_count=capture_result.chunk_count,
            neuron_count=capture_result.neuron_count,
            distill_mode=capture_result.distill_mode,
            export_path=None,
            checkpoint_ok=checkpoint.ok,
        )

    conn = connect(resolved_db)
    export_path: Path | None = None
    try:
        extra_neurons = 0
        if capture_result.neuron_count == 0:
            extra_neurons = _maybe_add_context_neuron(
                conn,
                transcript_path=transcript_path,
                session_id=capture_result.session_id,
            )

        if cfg.handover.export_markdown:
            rows = conn.execute(
                """
                SELECT subtype, title, content
                FROM nodes
                WHERE session_id = ? AND kind = 'memory'
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (capture_result.session_id, cfg.capture.max_auto_neurons_per_session),
            ).fetchall()
            exported = [
                (str(row[0] or "fact"), str(row[1]), str(row[2] or ""))
                for row in rows
            ]
            export_path = _write_handover_export(
                project_dir=project_dir,
                session_id=capture_result.session_id,
                neurons=exported,
            )

        conn.commit()
        if not confirm_writes(conn, expected_session_id=capture_result.session_id):
            logger.warning("write confirm failed for session_id=%s", capture_result.session_id)

        checkpoint = wal_checkpoint(conn)
    finally:
        conn.close()

    total_neurons = capture_result.neuron_count + extra_neurons
    return HandoverResult(
        session_id=capture_result.session_id,
        skipped=False,
        reason=None,
        chunk_count=capture_result.chunk_count,
        neuron_count=total_neurons,
        distill_mode=capture_result.distill_mode,
        export_path=export_path,
        checkpoint_ok=checkpoint.ok,
    )


def run_handover_from_stdin(
    raw: str,
    *,
    project_dir: Path | None = None,
    config: BrainConfig | None = None,
) -> HandoverResult:
    """Entry point for `brainkm handover --stdin`."""
    cwd = project_dir if project_dir is not None else Path.cwd()
    payload = parse_precompact_hook_payload(raw, cwd=cwd)
    session_id = payload.session_id or payload.conversation_id
    return run_handover(
        payload.transcript_path,
        project_dir=project_dir,
        config=config,
        session_id=session_id,
    )
