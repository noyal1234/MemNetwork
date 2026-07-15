"""Usage-feedback ranking: injected vs used neuron tracking."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _table_ready(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='neuron_feedback'"
    ).fetchone()
    return row is not None


def _ensure_row(conn: sqlite3.Connection, node_id: str) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO neuron_feedback (
          node_id, injected_count, used_count, ignored_count, updated_at
        ) VALUES (?, 0, 0, 0, ?)
        """,
        (node_id, _now()),
    )


def record_injected(conn: sqlite3.Connection, node_ids: list[str]) -> None:
    if not node_ids or not _table_ready(conn):
        return
    now = _now()
    for node_id in node_ids:
        _ensure_row(conn, node_id)
        conn.execute(
            """
            UPDATE neuron_feedback
            SET injected_count = injected_count + 1,
                last_injected = ?,
                updated_at = ?
            WHERE node_id = ?
            """,
            (now, now, node_id),
        )


def record_used(conn: sqlite3.Connection, node_ids: list[str]) -> None:
    if not node_ids or not _table_ready(conn):
        return
    now = _now()
    for node_id in node_ids:
        _ensure_row(conn, node_id)
        conn.execute(
            """
            UPDATE neuron_feedback
            SET used_count = used_count + 1,
                last_used = ?,
                updated_at = ?
            WHERE node_id = ?
            """,
            (now, now, node_id),
        )


def mark_ignored_since_injection(
    conn: sqlite3.Connection,
    *,
    session_id: str | None = None,
) -> int:
    """Increase ignored_count for neurons injected but never used.

    Uses last_injected vs last_used. Returns rows updated.
    """
    _ = session_id
    if not _table_ready(conn):
        return 0
    now = _now()
    cur = conn.execute(
        """
        UPDATE neuron_feedback
        SET ignored_count = ignored_count + 1,
            updated_at = ?
        WHERE injected_count > used_count
          AND (last_used IS NULL OR last_used < last_injected)
        """,
        (now,),
    )
    return int(cur.rowcount or 0)
