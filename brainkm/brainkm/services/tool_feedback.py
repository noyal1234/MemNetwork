"""Per-tool success/failure counters (migration 012_tool_feedback).

``tool_registry.py`` stores name+description for the tool-node cap; nothing
previously tracked whether a tool has been failing. ``PostToolUseFailure``
now feeds this table so a future pack could surface "the last N calls to X
failed" — that surfacing is out of scope here; this lands the counter only.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _table_ready(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tool_feedback'"
    ).fetchone()
    return row is not None


def _ensure_row(conn: sqlite3.Connection, tool_name: str) -> None:
    now = _now()
    conn.execute(
        """
        INSERT OR IGNORE INTO tool_feedback (
          tool_name, success_count, failure_count, updated_at
        ) VALUES (?, 0, 0, ?)
        """,
        (tool_name, now),
    )


def record_tool_result(conn: sqlite3.Connection, tool_name: str, *, failed: bool) -> None:
    """Bump success_count or failure_count for ``tool_name`` (no-op before migration)."""
    if not tool_name or not _table_ready(conn):
        return
    _ensure_row(conn, tool_name)
    now = _now()
    if failed:
        conn.execute(
            """
            UPDATE tool_feedback
            SET failure_count = failure_count + 1,
                last_failure = ?,
                updated_at = ?
            WHERE tool_name = ?
            """,
            (now, now, tool_name),
        )
    else:
        conn.execute(
            """
            UPDATE tool_feedback
            SET success_count = success_count + 1,
                last_success = ?,
                updated_at = ?
            WHERE tool_name = ?
            """,
            (now, now, tool_name),
        )


@dataclass(frozen=True)
class ToolFeedbackSummary:
    tool_name: str
    success_count: int
    failure_count: int
    last_failure: str | None


def get_tool_feedback(conn: sqlite3.Connection, tool_name: str) -> ToolFeedbackSummary | None:
    if not tool_name or not _table_ready(conn):
        return None
    row = conn.execute(
        """
        SELECT tool_name, success_count, failure_count, last_failure
        FROM tool_feedback WHERE tool_name = ?
        """,
        (tool_name,),
    ).fetchone()
    if row is None:
        return None
    return ToolFeedbackSummary(
        tool_name=row["tool_name"],
        success_count=int(row["success_count"]),
        failure_count=int(row["failure_count"]),
        last_failure=row["last_failure"],
    )


def get_tool_failure_rates(
    conn: sqlite3.Connection, *, min_calls: int = 5
) -> dict[str, float]:
    """tool_name -> failure rate, for tools with enough calls to be meaningful.

    First consumer of this table (record_tool_result previously wrote it with
    no reader) — surfaced via brain_stats.tool_failure_rates.
    """
    if not _table_ready(conn):
        return {}
    rows = conn.execute(
        """
        SELECT tool_name, success_count, failure_count
        FROM tool_feedback
        WHERE success_count + failure_count >= ?
        """,
        (min_calls,),
    ).fetchall()
    out: dict[str, float] = {}
    for row in rows:
        total = int(row["success_count"]) + int(row["failure_count"])
        if total:
            out[str(row["tool_name"])] = round(int(row["failure_count"]) / total, 3)
    return out
