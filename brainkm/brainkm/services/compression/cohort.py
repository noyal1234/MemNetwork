"""Sticky session-scoped engine canary assignment."""

from __future__ import annotations

import hashlib
import sqlite3

from brainkm.models.brain_config import CompressionConfig
from brainkm.services.audit import utc_now_iso
from brainkm.services.compression.types import ENGINE_VERSION


def _stable_bucket(session_id: str, salt: str) -> float:
    digest = hashlib.sha256(f"{salt}:{session_id}".encode()).hexdigest()
    # 0..1 from first 8 hex chars
    return int(digest[:8], 16) / 0xFFFFFFFF


def assign_session_cohort(
    conn: sqlite3.Connection,
    session_id: str,
    config: CompressionConfig,
) -> tuple[str, bool]:
    """Return (engine_version, is_canary). Sticky for the session lifetime."""
    if not session_id:
        return config.engine_version or ENGINE_VERSION, False

    row = conn.execute(
        """
        SELECT engine_version, canary
        FROM session_compression_cohort
        WHERE session_id = ?
        """,
        (session_id,),
    ).fetchone()
    if row is not None:
        return str(row[0]), bool(row[1])

    if config.engine_version_override:
        version = config.engine_version_override
        canary = True
    else:
        base = config.engine_version or ENGINE_VERSION
        canary_version = config.canary_engine_version or base
        pct = max(0.0, min(1.0, float(config.canary_pct)))
        canary = _stable_bucket(session_id, config.canary_salt) < pct
        version = canary_version if canary and canary_version != base else base

    conn.execute(
        """
        INSERT INTO session_compression_cohort (
          session_id, engine_version, canary, assigned_at
        ) VALUES (?, ?, ?, ?)
        """,
        (session_id, version, 1 if canary else 0, utc_now_iso()),
    )
    return version, canary


def get_session_engine_version(
    conn: sqlite3.Connection,
    session_id: str | None,
    config: CompressionConfig,
) -> str:
    if not session_id:
        return config.engine_version or ENGINE_VERSION
    version, _ = assign_session_cohort(conn, session_id, config)
    return version
