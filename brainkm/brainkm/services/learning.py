"""V2 learning loop state and co-activation helpers.

Persists learning signals to SQLite so Cursor hook subprocesses share state.
An in-memory window remains for the long-lived MCP server process.
"""

from __future__ import annotations

import sqlite3
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from brainkm.logging_config import get_logger
from brainkm.models.brain_config import BrainConfig
from brainkm.services.audit import utc_now_iso
from brainkm.services.memory import new_ulid
from brainkm.services.tool_registry import register_tool_node_idempotent

logger = get_logger("services.learning")

_INTERNAL_TOOLS = frozenset(
    {
        "remember",
        "recall",
        "context_pack",
        "session_status",
        "traverse",
        "forget",
        "brain_stats",
        "graph_sync",
        "__recall__",
    }
)


@dataclass
class _SessionEntry:
    tool_name: str
    neuron_ids: list[str]
    ts: str


@dataclass
class SessionLearningWindow:
    """In-process per-session window for learning signals."""

    windows: dict[str, deque[_SessionEntry]] = field(default_factory=dict)
    cap: int = 20

    def set_cap(self, cap: int) -> None:
        self.cap = cap
        for session_id, items in list(self.windows.items()):
            self.windows[session_id] = deque(items, maxlen=cap)

    def record_neuron_hits(self, session_id: str | None, node_ids: list[str]) -> None:
        if not session_id or not node_ids:
            return
        bucket = self.windows.setdefault(session_id, deque(maxlen=self.cap))
        bucket.append(_SessionEntry(tool_name="__recall__", neuron_ids=list(node_ids), ts=utc_now_iso()))

    def record_tool_use(self, session_id: str | None, tool_name: str, payload: dict[str, Any]) -> None:
        if not session_id or not tool_name:
            return
        bucket = self.windows.setdefault(session_id, deque(maxlen=self.cap))
        bucket.append(_SessionEntry(tool_name=tool_name, neuron_ids=[], ts=utc_now_iso()))
        if payload:
            logger.debug("session=%s recorded tool=%s", session_id, tool_name)

    def recent_neuron_ids(self, session_id: str | None) -> list[str]:
        if not session_id:
            return []
        seen: set[str] = set()
        ordered: list[str] = []
        for entry in self.windows.get(session_id, ()):
            for node_id in entry.neuron_ids:
                if node_id not in seen:
                    seen.add(node_id)
                    ordered.append(node_id)
        return ordered

    def recent_tool_names(self, session_id: str | None) -> list[str]:
        if not session_id:
            return []
        return [entry.tool_name for entry in self.windows.get(session_id, ()) if entry.tool_name != "__recall__"]

    def reset(self) -> None:
        self.windows.clear()


_window = SessionLearningWindow()


def get_learning_window() -> SessionLearningWindow:
    return _window


def persist_neuron_hits(
    conn: sqlite3.Connection,
    session_id: str | None,
    node_ids: list[str],
    *,
    source: str = "recall",
    cap: int | None = None,
) -> None:
    """Write neuron hits to SQLite and the in-memory learning window.

    use_count is incremented later via flush_use_counts (SessionEnd or opportunistic stale flush).
    """
    if not session_id or not node_ids:
        return
    from brainkm.services.session_activity import get_session_activity

    window = get_learning_window()
    if cap is not None:
        window.set_cap(cap)
    window.record_neuron_hits(session_id, node_ids)
    get_session_activity().track(session_id, node_ids)
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


def persist_tool_use(
    conn: sqlite3.Connection,
    session_id: str | None,
    tool_name: str,
    payload: dict[str, Any],
    *,
    source: str = "post_tool",
    cap: int | None = None,
) -> None:
    """Write a tool-use event to SQLite and the in-memory window."""
    if not session_id or not tool_name:
        return
    window = get_learning_window()
    if cap is not None:
        window.set_cap(cap)
    window.record_tool_use(session_id, tool_name, payload)
    conn.execute(
        """
        INSERT INTO session_activity (
          id, session_id, kind, node_id, tool_name, source, created_at
        ) VALUES (?, ?, 'tool_use', NULL, ?, ?, ?)
        """,
        (new_ulid(), session_id, tool_name, source, utc_now_iso()),
    )


def load_recent_neuron_ids(
    conn: sqlite3.Connection,
    session_id: str | None,
    *,
    limit: int = 40,
) -> list[str]:
    """Distinct neuron ids for a session, preferring DB (cross-process) then memory."""
    if not session_id:
        return []
    rows = conn.execute(
        """
        SELECT node_id
        FROM session_activity
        WHERE session_id = ?
          AND kind = 'neuron_hit'
          AND node_id IS NOT NULL
        ORDER BY created_at ASC
        """,
        (session_id,),
    ).fetchall()
    seen: set[str] = set()
    ordered: list[str] = []
    for row in rows:
        node_id = row[0]
        if node_id not in seen:
            seen.add(node_id)
            ordered.append(node_id)
    if ordered:
        return ordered[-limit:]
    return get_learning_window().recent_neuron_ids(session_id)[-limit:]


def load_recent_tool_names(
    conn: sqlite3.Connection,
    session_id: str | None,
    *,
    limit: int = 40,
) -> list[str]:
    """Tool names recorded for a session (DB preferred for hook path)."""
    if not session_id:
        return []
    rows = conn.execute(
        """
        SELECT tool_name
        FROM session_activity
        WHERE session_id = ?
          AND kind = 'tool_use'
          AND tool_name IS NOT NULL
          AND tool_name != '__recall__'
        ORDER BY created_at ASC
        """,
        (session_id,),
    ).fetchall()
    names = [row[0] for row in rows]
    if names:
        return names[-limit:]
    return get_learning_window().recent_tool_names(session_id)[-limit:]


def upsert_co_activation(conn: sqlite3.Connection, a: str, b: str) -> None:
    """Create or increment canonical co_activated edge."""
    if not a or not b or a == b:
        return
    from_id, to_id = (a, b) if a < b else (b, a)
    now = utc_now_iso()
    updated = conn.execute(
        """
        UPDATE edges
        SET weight = weight + 1, updated_at = ?
        WHERE from_id = ? AND to_id = ? AND relationship = 'co_activated'
        """,
        (now, from_id, to_id),
    )
    if updated.rowcount:
        return
    conn.execute(
        """
        INSERT OR IGNORE INTO edges (id, from_id, to_id, relationship, weight, created_at, updated_at)
        VALUES (?, ?, ?, 'co_activated', 1.0, ?, ?)
        """,
        (new_ulid(), from_id, to_id, now, now),
    )


def process_post_tool(
    conn: sqlite3.Connection,
    session_id: str | None,
    tool_name: str,
    payload: dict[str, Any],
    *,
    config: BrainConfig,
) -> None:
    """Update learning state after a post-tool hook event."""
    persist_tool_use(
        conn,
        session_id,
        tool_name,
        payload,
        source="post_tool",
        cap=config.learning.session_window_size,
    )

    neuron_ids = load_recent_neuron_ids(conn, session_id, limit=config.learning.session_window_size)
    if neuron_ids:
        from brainkm.services.feedback import record_used

        record_used(conn, list(neuron_ids))
    if len(neuron_ids) >= 2:
        for index, first in enumerate(neuron_ids):
            for second in neuron_ids[index + 1 :]:
                upsert_co_activation(conn, first, second)

    if tool_name and tool_name not in _INTERNAL_TOOLS:
        try:
            register_tool_node_idempotent(
                conn,
                name=tool_name,
                max_tools=config.learning.max_tool_nodes,
            )
        except ValueError as exc:
            logger.info("tool registry skipped: %s", exc)

    from brainkm.services.procedures import check_and_promote

    check_and_promote(conn, session_id, config=config)
