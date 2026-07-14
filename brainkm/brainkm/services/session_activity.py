"""Track neurons recalled/injected per session for use_count flush at SessionEnd.

Persists to SQLite so Cursor hook subprocesses (SessionStart / PreToolUse / SessionEnd)
share the same activity log. An in-memory cache remains for the long-lived MCP process.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from brainkm.services.audit import utc_now_iso
from brainkm.services.memory import new_ulid

# Sentinel session for MCP calls that omit session_id (session_activity.session_id NOT NULL).
ANON_SESSION_ID = "__anon__"
TOOL_USE_RETENTION_DAYS = 30


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
    Deletes flushed neuron_hit rows for the session.
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


def flush_stale_session_hits(
    conn: sqlite3.Connection,
    *,
    older_than_hours: float = 6.0,
) -> int:
    """Opportunistically flush neuron hits for sessions idle longer than the threshold.

    Used when SessionEnd never ran (crash/kill) so use_count still advances.
    """
    cutoff = (datetime.now(UTC) - timedelta(hours=older_than_hours)).isoformat()
    rows = conn.execute(
        """
        SELECT session_id, MAX(created_at) AS last_at
        FROM session_activity
        WHERE kind = 'neuron_hit'
          AND session_id IS NOT NULL
          AND session_id != ?
        GROUP BY session_id
        HAVING last_at < ?
        """,
        (ANON_SESSION_ID, cutoff),
    ).fetchall()
    total = 0
    for row in rows:
        total += flush_use_counts(conn, row[0])
    return total


def prune_old_tool_use(
    conn: sqlite3.Connection,
    *,
    retention_days: int = TOOL_USE_RETENTION_DAYS,
) -> int:
    """Delete tool_use activity rows older than retention_days."""
    cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
    cursor = conn.execute(
        """
        DELETE FROM session_activity
        WHERE kind = 'tool_use' AND created_at < ?
        """,
        (cutoff,),
    )
    return int(cursor.rowcount or 0)


def record_mcp_tool_use(
    conn: sqlite3.Connection,
    session_id: str | None,
    tool_name: str,
    *,
    abstained: bool = False,
    result_count: int | None = None,
) -> None:
    """Log an MCP tool invocation (works without a real session_id)."""
    if not tool_name:
        return
    sid = session_id or ANON_SESSION_ID
    source = "mcp_abstained" if abstained else "mcp"
    # Encode light result metadata in tool_name suffix when useful for stats.
    logged_name = tool_name
    if result_count is not None and tool_name in {"recall", "context_pack", "traverse"}:
        logged_name = f"{tool_name}:{result_count}"
    conn.execute(
        """
        INSERT INTO session_activity (
          id, session_id, kind, node_id, tool_name, source, created_at
        ) VALUES (?, ?, 'tool_use', NULL, ?, ?, ?)
        """,
        (new_ulid(), sid, logged_name, source, utc_now_iso()),
    )
