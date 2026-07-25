"""Dual-store compressed views keyed by (neuron_id, body_hash, engine_version, intensity)."""

from __future__ import annotations

import hashlib
import sqlite3

from brainkm.services.audit import utc_now_iso
from brainkm.services.memory import new_ulid, token_count


def body_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def get_compressed_view(
    conn: sqlite3.Connection,
    *,
    neuron_id: str,
    full_body: str,
    engine_version: str,
    intensity: str,
) -> str | None:
    h = body_hash(full_body)
    row = conn.execute(
        """
        SELECT compressed_text
        FROM compression_views
        WHERE neuron_id = ?
          AND body_hash = ?
          AND engine_version = ?
          AND intensity = ?
        """,
        (neuron_id, h, engine_version, intensity),
    ).fetchone()
    return str(row[0]) if row else None


def put_compressed_view(
    conn: sqlite3.Connection,
    *,
    neuron_id: str,
    full_body: str,
    compressed_text: str,
    engine_version: str,
    intensity: str,
) -> None:
    h = body_hash(full_body)
    conn.execute(
        """
        INSERT INTO compression_views (
          neuron_id, body_hash, engine_version, intensity,
          compressed_text, tokens_in, tokens_out, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(neuron_id, body_hash, engine_version, intensity) DO UPDATE SET
          compressed_text = excluded.compressed_text,
          tokens_in = excluded.tokens_in,
          tokens_out = excluded.tokens_out,
          created_at = excluded.created_at
        """,
        (
            neuron_id,
            h,
            engine_version,
            intensity,
            compressed_text,
            token_count(full_body),
            token_count(compressed_text),
            utc_now_iso(),
        ),
    )


def invalidate_neuron_views(conn: sqlite3.Connection, neuron_id: str) -> int:
    cur = conn.execute(
        "DELETE FROM compression_views WHERE neuron_id = ?",
        (neuron_id,),
    )
    return int(cur.rowcount or 0)


def log_compression_event(
    conn: sqlite3.Connection,
    *,
    session_id: str | None,
    surface: str,
    composition_mode: str,
    engine_id: str,
    tokens_in: int,
    tokens_out: int,
    skipped_reason: str | None = None,
    latency_ms: float | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO compression_events (
          id, session_id, surface, composition_mode, engine_id,
          tokens_in, tokens_out, skipped_reason, latency_ms, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_ulid(),
            session_id,
            surface,
            composition_mode,
            engine_id,
            tokens_in,
            tokens_out,
            skipped_reason,
            latency_ms,
            utc_now_iso(),
        ),
    )


def compression_rollups(conn: sqlite3.Connection, *, days: int = 7) -> dict[str, object]:
    from datetime import UTC, datetime, timedelta

    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """
        SELECT surface,
               COUNT(*) AS n,
               COALESCE(SUM(tokens_in), 0) AS tin,
               COALESCE(SUM(tokens_out), 0) AS tout,
               COALESCE(AVG(latency_ms), 0) AS lat
        FROM compression_events
        WHERE created_at >= ?
        GROUP BY surface
        """,
        (cutoff,),
    ).fetchall()
    by_surface: dict[str, dict[str, float | int]] = {}
    for row in rows:
        tin, tout = int(row[2]), int(row[3])
        by_surface[str(row[0])] = {
            "events": int(row[1]),
            "tokens_in": tin,
            "tokens_out": tout,
            "saved": max(0, tin - tout),
            "avg_latency_ms": float(row[4] or 0.0),
        }
    return {"days": days, "by_surface": by_surface}
