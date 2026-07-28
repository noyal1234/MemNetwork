"""V2 learning loop state and co-activation helpers.

Persists learning signals to SQLite so Cursor hook subprocesses share state.
An in-memory window remains for the long-lived MCP server process.

Hebbian hardening: pairwise episodes only from capped persist_neuron_hits;
saturating co_activated weights; compound idle decay via decayed_at checkpoint.
"""

from __future__ import annotations

import json
import sqlite3
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
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

# Parent conversation keys only — never subagent_id (inject dedupe).
_INJECT_SESSION_KEYS = (
    "session_id",
    "sessionId",
    "conversation_id",
    "conversationId",
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
        bucket.append(
            _SessionEntry(tool_name="__recall__", neuron_ids=list(node_ids), ts=utc_now_iso())
        )

    def record_tool_use(
        self, session_id: str | None, tool_name: str, payload: dict[str, Any]
    ) -> None:
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
        return [
            entry.tool_name
            for entry in self.windows.get(session_id, ())
            if entry.tool_name != "__recall__"
        ]

    def reset(self) -> None:
        self.windows.clear()


_window = SessionLearningWindow()


def get_learning_window() -> SessionLearningWindow:
    return _window


def inject_session_id_from_payload(data: dict[str, object]) -> str | None:
    """Parent session id for inject dedupe — never subagent_id."""
    for key in _INJECT_SESSION_KEYS:
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _unique_capped(node_ids: list[str], cap: int | None) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for node_id in node_ids:
        if not node_id or node_id in seen:
            continue
        seen.add(node_id)
        ordered.append(node_id)
    if cap is not None and cap > 0:
        return ordered[:cap]
    return ordered


def _mark_pending_coact(
    conn: sqlite3.Connection,
    session_id: str,
    node_ids: list[str],
) -> None:
    """REPLACE pending episode set (targeted retrieval only)."""
    if not node_ids:
        return
    now = utc_now_iso()
    payload = json.dumps(node_ids)
    conn.execute(
        """
        INSERT INTO session_learning_state (
          session_id, pending_node_ids, pending_coact, updated_at
        ) VALUES (?, ?, 1, ?)
        ON CONFLICT(session_id) DO UPDATE SET
          pending_node_ids = excluded.pending_node_ids,
          pending_coact = 1,
          updated_at = excluded.updated_at
        """,
        (session_id, payload, now),
    )


def _peek_pending_node_ids(conn: sqlite3.Connection, session_id: str | None) -> list[str]:
    """Read lingering pending_node_ids; missing row → empty (no exception)."""
    if not session_id:
        return []
    row = conn.execute(
        """
        SELECT pending_node_ids
        FROM session_learning_state
        WHERE session_id = ?
        """,
        (session_id,),
    ).fetchone()
    if row is None or not row[0]:
        return []
    try:
        parsed = json.loads(row[0])
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if item]


def _consume_pending_coact(conn: sqlite3.Connection, session_id: str | None) -> list[str] | None:
    """CAS: claim pending episode under write lock; leave pending_node_ids populated.

    Uses BEGIN IMMEDIATE when not already in a transaction. Within an open
    transaction, UPDATE acquires the write lock before SELECT.
    """
    if not session_id:
        return None
    own_txn = False
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
        own_txn = True
    try:
        cur = conn.execute(
            """
            UPDATE session_learning_state
            SET pending_coact = 0
            WHERE session_id = ? AND pending_coact = 1
            """,
            (session_id,),
        )
        if cur.rowcount != 1:
            return None
        row = conn.execute(
            """
            SELECT pending_node_ids
            FROM session_learning_state
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
        if row is None or not row[0]:
            return []
        try:
            parsed = json.loads(row[0])
        except (TypeError, json.JSONDecodeError):
            return []
        if not isinstance(parsed, list):
            return []
        return [str(item) for item in parsed if item]
    finally:
        # Caller owns commit when we joined an outer transaction; when we opened
        # IMMEDIATE ourselves, leave it open for the caller's commit.
        _ = own_txn


def delete_session_learning_state(conn: sqlite3.Connection, session_id: str | None) -> None:
    """Drop pending episode / learning state for a session (SessionEnd DROP)."""
    if not session_id:
        return
    conn.execute(
        "DELETE FROM session_learning_state WHERE session_id = ?",
        (session_id,),
    )


def purge_session_learning_state(
    conn: sqlite3.Connection,
    *,
    retention_days: int = 14,
) -> int:
    """Delete orphan session_learning_state rows older than retention_days."""
    cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
    cur = conn.execute(
        "DELETE FROM session_learning_state WHERE updated_at < ?",
        (cutoff,),
    )
    return int(cur.rowcount or 0)


def persist_neuron_hits(
    conn: sqlite3.Connection,
    session_id: str | None,
    node_ids: list[str],
    *,
    source: str = "recall",
    cap: int | None = None,
) -> None:
    """Write neuron hits, open pairwise episode, and record ignore-eligible inject.

    use_count is incremented later via flush_use_counts (SessionEnd or opportunistic stale flush).
    """
    if not session_id or not node_ids:
        return
    from brainkm.services.feedback import record_injected
    from brainkm.services.session_activity import get_session_activity

    capped = _unique_capped(node_ids, cap)
    if not capped:
        return

    window = get_learning_window()
    if cap is not None:
        window.set_cap(cap)
    window.record_neuron_hits(session_id, capped)
    get_session_activity().track(session_id, capped)
    now = utc_now_iso()
    for node_id in capped:
        conn.execute(
            """
            INSERT INTO session_activity (
              id, session_id, kind, node_id, tool_name, source, created_at
            ) VALUES (?, ?, 'neuron_hit', ?, '__recall__', ?, ?)
            """,
            (new_ulid(), session_id, node_id, source, now),
        )

    _mark_pending_coact(conn, session_id, capped)
    record_injected(conn, capped, session_id=session_id)


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
    """Distinct neuron ids for a session, preferring DB (cross-process) then memory.

    Includes ambient and targeted ``neuron_hit`` rows.
    """
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


def upsert_co_activation(
    conn: sqlite3.Connection,
    a: str,
    b: str,
    *,
    delta: float = 1.0,
    max_weight: float = 10.0,
) -> None:
    """Create or saturating-increment canonical co_activated edge; clear decayed_at."""
    if not a or not b or a == b:
        return
    from_id, to_id = (a, b) if a < b else (b, a)
    now = utc_now_iso()
    start = min(float(delta), float(max_weight))
    updated = conn.execute(
        """
        UPDATE edges
        SET weight = MIN(?, weight + ?),
            updated_at = ?,
            decayed_at = NULL
        WHERE from_id = ? AND to_id = ? AND relationship = 'co_activated'
        """,
        (max_weight, delta, now, from_id, to_id),
    )
    if updated.rowcount:
        return
    # Older DBs may lack decayed_at until migrate; try with column then without.
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO edges (
              id, from_id, to_id, relationship, weight, created_at, updated_at, decayed_at
            ) VALUES (?, ?, ?, 'co_activated', ?, ?, ?, NULL)
            """,
            (new_ulid(), from_id, to_id, start, now, now),
        )
    except sqlite3.OperationalError:
        conn.execute(
            """
            INSERT OR IGNORE INTO edges (
              id, from_id, to_id, relationship, weight, created_at, updated_at
            ) VALUES (?, ?, ?, 'co_activated', ?, ?, ?)
            """,
            (new_ulid(), from_id, to_id, start, now, now),
        )


def _parse_edge_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _advance_by_days(checkpoint: datetime, days: float) -> datetime:
    return checkpoint + timedelta(days=days)


def decay_co_activation_edges(
    conn: sqlite3.Connection,
    *,
    idle_days: int = 30,
    decay_factor: float = 0.5,
    min_weight: float = 0.3,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict[str, int]:
    """Compound idle decay for co_activated edges; DELETE below min_weight.

    Periods from COALESCE(decayed_at, updated_at); checkpoint advances by
    periods * idle_days (not wall-clock now). Does not stomp updated_at.
    """
    clock = now or datetime.now(UTC)
    rows = conn.execute(
        """
        SELECT id, weight, updated_at, decayed_at
        FROM edges
        WHERE relationship = 'co_activated'
        """
    ).fetchall()
    decayed = 0
    deleted = 0
    for row in rows:
        edge_id = row[0]
        weight = float(row[1])
        updated_at = _parse_edge_ts(row[2])
        decayed_at = _parse_edge_ts(row[3]) if len(row) > 3 else None
        if updated_at is None:
            continue
        days_since_reinforce = (clock - updated_at).total_seconds() / 86400.0
        if days_since_reinforce < idle_days:
            continue
        checkpoint = decayed_at or updated_at
        days_since_ckpt = (clock - checkpoint).total_seconds() / 86400.0
        periods = int(days_since_ckpt // idle_days)
        if periods < 1:
            continue
        new_weight = weight * (decay_factor**periods)
        new_ckpt = _advance_by_days(checkpoint, float(periods * idle_days))
        if new_weight < min_weight:
            deleted += 1
            if not dry_run:
                conn.execute("DELETE FROM edges WHERE id = ?", (edge_id,))
            continue
        decayed += 1
        if not dry_run:
            conn.execute(
                """
                UPDATE edges
                SET weight = ?, decayed_at = ?
                WHERE id = ?
                """,
                (new_weight, new_ckpt.isoformat(), edge_id),
            )
    return {"decayed": decayed, "deleted": deleted}


def process_post_tool(
    conn: sqlite3.Connection,
    session_id: str | None,
    tool_name: str,
    payload: dict[str, Any],
    *,
    config: BrainConfig,
) -> None:
    """Update learning state after a post-tool hook event."""
    learning = config.learning
    persist_tool_use(
        conn,
        session_id,
        tool_name,
        payload,
        source="post_tool",
        cap=learning.session_window_size,
    )

    # Episode-gated: "used" fires once per freshly-claimed episode (mirrors the
    # co-activation gate below), never per subsequent unrelated tool call — the
    # CAS in _consume_pending_coact already guarantees at-most-once delivery.
    consumed = _consume_pending_coact(conn, session_id)
    if consumed:
        from brainkm.services.feedback import record_used

        record_used(conn, list(consumed))

    if consumed is not None and len(consumed) >= 2:
        for index, first in enumerate(consumed):
            for second in consumed[index + 1 :]:
                upsert_co_activation(
                    conn,
                    first,
                    second,
                    delta=learning.co_activation_delta,
                    max_weight=learning.co_activation_max_weight,
                )

    if tool_name and tool_name not in _INTERNAL_TOOLS:
        try:
            register_tool_node_idempotent(
                conn,
                name=tool_name,
                max_tools=learning.max_tool_nodes,
            )
        except ValueError as exc:
            logger.info("tool registry skipped: %s", exc)

    from brainkm.services.procedures import check_and_promote

    check_and_promote(conn, session_id, config=config)
