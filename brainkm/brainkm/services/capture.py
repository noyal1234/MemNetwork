"""Session capture pipeline — chunks first, then distill, then neurons."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from brainkm.adapters.distill import distill_rounds_with_timeout, get_distill_adapter
from brainkm.adapters.redaction import RedactionBlockedError
from brainkm.adapters.transcript_v1 import parse_transcript_file
from brainkm.db.connection import connect
from brainkm.db.migrate import migrate
from brainkm.db.paths import brain_db_path
from brainkm.logging_config import get_logger
from brainkm.models.brain_config import BrainConfig
from brainkm.models.distill import CaptureResult
from brainkm.services.chunks import (
    link_chunk_sources,
    map_round_chunk_ids,
    persist_message_chunks,
)
from brainkm.services.config_loader import load_brain_config
from brainkm.services.memory import create_neuron, new_ulid
from brainkm.services.quality import filter_distilled
from brainkm.services.review import enqueue_for_review

logger = get_logger("services.capture")


def transcript_fingerprint(raw_bytes: bytes) -> str:
    return hashlib.sha256(raw_bytes).hexdigest()


def is_session_ingested(conn: sqlite3.Connection, fingerprint: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM ingested_sessions WHERE fingerprint = ?",
        (fingerprint,),
    ).fetchone()
    return row is not None


def mark_session_ingested(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    fingerprint: str,
    distill_mode: str,
    neuron_count: int,
) -> None:
    from brainkm.services.audit import utc_now_iso

    conn.execute(
        """
        INSERT INTO ingested_sessions (
          session_id, fingerprint, distill_mode, neuron_count, ingested_at
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
          fingerprint = excluded.fingerprint,
          distill_mode = excluded.distill_mode,
          neuron_count = excluded.neuron_count,
          ingested_at = excluded.ingested_at
        """,
        (session_id, fingerprint, distill_mode, neuron_count, utc_now_iso()),
    )


def capture_transcript_file(
    transcript_path: Path,
    *,
    project_dir: Path | None = None,
    config: BrainConfig | None = None,
    session_id: str | None = None,
    db_path: Path | None = None,
    skip_duplicate: bool = True,
    distill_timeout_seconds: int | None = None,
    allowed_subtypes: set[str] | None = None,
) -> CaptureResult:
    """Full capture pipeline for one transcript file."""
    cfg = config or load_brain_config(project_dir)
    review_project_dir = (
        project_dir
        if project_dir is not None
        else (db_path.parent.parent if db_path is not None else None)
    )
    if not cfg.capture.transcripts:
        return CaptureResult(
            session_id=session_id or transcript_path.stem,
            skipped=True,
            reason="capture.transcripts disabled",
            chunk_count=0,
            neuron_count=0,
            distill_mode=cfg.capture.distill_mode,
        )

    raw_bytes = transcript_path.read_bytes()
    fingerprint = transcript_fingerprint(raw_bytes)
    parsed = parse_transcript_file(transcript_path, session_id=session_id)
    resolved_db = db_path if db_path is not None else brain_db_path(project_dir)

    if db_path is None and project_dir is not None:
        migrate(db_path=resolved_db, run_integrity_check=False)
    elif db_path is not None:
        migrate(db_path=resolved_db, run_integrity_check=False)

    conn = connect(resolved_db)
    try:
        if skip_duplicate and is_session_ingested(conn, fingerprint):
            logger.info("Skipping duplicate transcript fingerprint %s", fingerprint[:12])
            return CaptureResult(
                session_id=parsed.session_id,
                skipped=True,
                reason="duplicate fingerprint",
                chunk_count=0,
                neuron_count=0,
                distill_mode=cfg.capture.distill_mode,
            )

        stored_chunks = persist_message_chunks(conn, parsed)
        round_chunk_ids = map_round_chunk_ids(parsed, stored_chunks)

        adapter = get_distill_adapter(cfg, conn=conn)
        distilled, distill_mode = distill_rounds_with_timeout(
            adapter,
            parsed.rounds,
            round_chunk_ids=round_chunk_ids,
            max_total=cfg.capture.max_auto_neurons_per_session,
            timeout_seconds=distill_timeout_seconds,
            config=cfg,
        )
        distilled = filter_distilled(
            distilled,
            max_count=cfg.capture.max_auto_neurons_per_session,
        )

        neuron_count = 0
        for item in distilled:
            if allowed_subtypes is not None and item.subtype not in allowed_subtypes:
                continue
            if not item.is_atomic():
                continue
            try:
                record = create_neuron(
                    conn,
                    title=item.title,
                    content=item.body,
                    kind="memory",
                    subtype=item.subtype,
                    tags=item.tags,
                    source=f"capture:{distill_mode}",
                    session_id=parsed.session_id,
                    node_id=new_ulid(),
                    confidence=item.confidence,
                )
            except RedactionBlockedError as exc:
                logger.warning("Skipped distilled neuron blocked by redaction: %s", exc)
                continue

            link_chunk_sources(conn, chunk_ids=item.chunk_ids, neuron_id=record.id)
            if item.confidence < cfg.learning.auto_capture_confidence:
                enqueue_for_review(conn, record.id, project_dir=review_project_dir)
            neuron_count += 1

        mark_session_ingested(
            conn,
            session_id=parsed.session_id,
            fingerprint=fingerprint,
            distill_mode=distill_mode,
            neuron_count=neuron_count,
        )
        conn.commit()

        logger.info(
            "Captured session %s: %d chunks, %d neurons (%s)",
            parsed.session_id,
            len(stored_chunks),
            neuron_count,
            distill_mode,
        )
        return CaptureResult(
            session_id=parsed.session_id,
            skipped=False,
            reason=None,
            chunk_count=len(stored_chunks),
            neuron_count=neuron_count,
            distill_mode=distill_mode,
        )
    finally:
        conn.close()
