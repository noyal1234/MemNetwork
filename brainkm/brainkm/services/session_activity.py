"""Track neurons recalled/injected per session for use_count flush at SessionEnd."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from brainkm.services.audit import utc_now_iso


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


def flush_use_counts(conn: sqlite3.Connection, session_id: str | None) -> int:
    """Increment use_count for neurons recalled/injected this session."""
    node_ids = _tracker.pop(session_id)
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
    return updated
