"""Track neurons recalled/injected per session for use_count flush at SessionEnd.

Persists to SQLite so Cursor hook subprocesses (SessionStart / PreToolUse / SessionEnd)
share the same activity log. An in-memory cache remains for the long-lived MCP process.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from brainkm.services.audit import utc_now_iso
from brainkm.services.memory import new_ulid


@dataclass
class SessionActivityTracker:
    recalled_nodes: dict[str, set[str]] = field(default_factory=dict)

    def track(self, session_id: str | None, node_ids: list[str]) -> None:
        if not session_id or not node_ids:
            return
        bucket = self.recalled_nodes.setdefault(session_id, set())
        bucket.update(node_ids)

    def pop(self, session_id: str | None) -> set[str]:
        if not session_id:
            return set()
        return self.recalled_nodes.pop(session_id, set())


_tracker = SessionActivityTracker()


def get_session_activity() -> SessionActivityTracker:
    return _tracker


def record_neuron_activity(
    conn: sqlite3.Connection,
    session_id: str | None,
    node_ids: list[str],
    *,
    source: str = "activity",
) -> None:
    """Persist neuron hits for a session (write-through) and update in-memory tracker."""
    if not session_id or not node_ids:
        return
    _tracker.track(session_id, node_ids)
    now = utc_now_iso()
    for node_id in node_ids:
        conn.execute(
            """
            INSERT INTO session_activity (
              id, session_id, kind, node_id, tool_name, source, created_at
            ) VALUES (?, ?, 'neuron_hit', ?, '__recall__', ?, ?)
            """,
            (new_ulid(), session_id, node_id, source, now),
        )


def load_session_neuron_ids(conn: sqlite3.Connection, session_id: str | None) -> set[str]:
    """Load distinct neuron ids recorded for a session from SQLite."""
    if not session_id:
        return set()
    rows = conn.execute(
        """
        SELECT DISTINCT node_id
        FROM session_activity
        WHERE session_id = ?
          AND kind = 'neuron_hit'
          AND node_id IS NOT NULL
        """,
        (session_id,),
    ).fetchall()
    return {row[0] for row in rows}


def flush_use_counts(conn: sqlite3.Connection, session_id: str | None) -> int:
    """Increment use_count for neurons recalled/injected this session.

    Merges in-memory tracker state with rows persisted by other hook subprocesses.
    """
    node_ids = _tracker.pop(session_id)
    node_ids |= load_session_neuron_ids(conn, session_id)
    if not node_ids:
        return 0

    now = utc_now_iso()
    updated = 0
    for node_id in node_ids:
        cursor = conn.execute(
            """
            UPDATE nodes
            SET use_count = use_count + 1, updated_at = ?
            WHERE id = ? AND valid_until IS NULL
            """,
            (now, node_id),
        )
        updated += cursor.rowcount

    if session_id:
        conn.execute(
            "DELETE FROM session_activity WHERE session_id = ? AND kind = 'neuron_hit'",
            (session_id,),
        )
    return updated
