"""Append-only audit_log helpers — single source of truth for temporal state."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

AuditEventType = str


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def append_event(
    conn: sqlite3.Connection,
    event_type: AuditEventType,
    *,
    node_id: str | None = None,
    edge_id: str | None = None,
    payload: dict[str, Any] | None = None,
    ts: str | None = None,
) -> int:
    """Insert an audit_log row. Returns the new row id."""
    timestamp = ts or utc_now_iso()
    payload_json = json.dumps(payload or {}, separators=(",", ":"), sort_keys=True)
    cursor = conn.execute(
        """
        INSERT INTO audit_log (event_type, node_id, edge_id, payload, ts)
        VALUES (?, ?, ?, ?, ?)
        """,
        (event_type, node_id, edge_id, payload_json, timestamp),
    )
    return int(cursor.lastrowid)


def list_node_events(
    conn: sqlite3.Connection,
    node_id: str,
    *,
    event_type: str | None = None,
) -> list[sqlite3.Row]:
    if event_type is None:
        return conn.execute(
            """
            SELECT id, event_type, node_id, edge_id, payload, ts
            FROM audit_log
            WHERE node_id = ?
            ORDER BY ts ASC, id ASC
            """,
            (node_id,),
        ).fetchall()

    return conn.execute(
        """
        SELECT id, event_type, node_id, edge_id, payload, ts
        FROM audit_log
        WHERE node_id = ? AND event_type = ?
        ORDER BY ts ASC, id ASC
        """,
        (node_id, event_type),
    ).fetchall()
