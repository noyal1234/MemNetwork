"""Persist session chunks and chunk_sources provenance."""

from __future__ import annotations

import sqlite3

from brainkm.adapters.capture import CaptureChunk, prepare_capture_chunk
from brainkm.adapters.redaction import RedactionBlockedError
from brainkm.logging_config import get_logger
from brainkm.models.distill import ParsedTranscript, StoredChunk
from brainkm.services.audit import append_event, utc_now_iso
from brainkm.services.memory import new_ulid

logger = get_logger("services.chunks")


def persist_message_chunks(
    conn: sqlite3.Connection,
    transcript: ParsedTranscript,
    *,
    ts: str | None = None,
) -> list[StoredChunk]:
    """Persist one session_chunks row per transcript message after redaction.

    Blocked messages are skipped (logged) so one secret does not abort the session.
    """
    timestamp = ts or utc_now_iso()
    stored: list[StoredChunk] = []

    for message in transcript.messages:
        try:
            prepared = prepare_capture_chunk(
                CaptureChunk(
                    content=message.text,
                    role=message.role,
                    session_id=transcript.session_id,
                )
            )
        except RedactionBlockedError as exc:
            logger.warning(
                "Skipped session chunk blocked by redaction session=%s role=%s: %s",
                transcript.session_id,
                message.role,
                exc,
            )
            continue
        chunk_id = new_ulid()
        conn.execute(
            """
            INSERT INTO session_chunks (id, session_id, role, content, ts)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                chunk_id,
                transcript.session_id,
                message.role,
                prepared.chunk.content,
                timestamp,
            ),
        )
        stored.append(
            StoredChunk(
                id=chunk_id,
                session_id=transcript.session_id,
                role=message.role,
                content=prepared.chunk.content,
                ts=timestamp,
                line_no=message.line_no,
            )
        )
    return stored


def map_round_chunk_ids(
    transcript: ParsedTranscript,
    stored_chunks: list[StoredChunk],
) -> dict[int, list[str]]:
    """Map round index to chunk IDs via message line_no (skips blocked messages)."""
    message_line_to_id = {
        chunk.line_no: chunk.id for chunk in stored_chunks if chunk.line_no is not None
    }

    round_map: dict[int, list[str]] = {}
    for round_ in transcript.rounds:
        ids: list[str] = []
        for message in round_.messages:
            chunk_id = message_line_to_id.get(message.line_no)
            if chunk_id and chunk_id not in ids:
                ids.append(chunk_id)
        round_map[round_.round_index] = ids
    return round_map


def link_chunk_sources(
    conn: sqlite3.Connection,
    *,
    chunk_ids: list[str],
    neuron_id: str,
    distill_ts: str | None = None,
) -> None:
    timestamp = distill_ts or utc_now_iso()
    for chunk_id in chunk_ids:
        conn.execute(
            """
            INSERT OR IGNORE INTO chunk_sources (chunk_id, neuron_id, distill_ts)
            VALUES (?, ?, ?)
            """,
            (chunk_id, neuron_id, timestamp),
        )

    append_event(
        conn,
        "distilled_from",
        node_id=neuron_id,
        payload={"chunk_ids": chunk_ids},
        ts=timestamp,
    )
