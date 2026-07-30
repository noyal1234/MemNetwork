"""Usage-feedback ranking: injected vs used neuron tracking."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from brainkm.services.memory import new_ulid


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


def record_injected(conn: sqlite3.Connection, node_ids: list[str], *, session_id: str) -> None:
    """Increment injected_count once per (session_id, node) via atomic INSERT OR IGNORE.

    ``session_id`` is required (no default) so missed call sites fail loudly.
    """
    if not session_id:
        raise TypeError("session_id is required for record_injected")
    if not node_ids or not _table_ready(conn):
        return
    now = _now()
    for node_id in node_ids:
        if not node_id:
            continue
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO session_activity (
              id, session_id, kind, node_id, tool_name, source, created_at
            ) VALUES (?, ?, 'injected', ?, NULL, 'inject', ?)
            """,
            (new_ulid(), session_id, node_id, now),
        )
        if cur.rowcount != 1:
            continue
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


def record_explicit_feedback(
    conn: sqlite3.Connection,
    node_ids: list[str],
    signal: str,
) -> list[str]:
    """Explicit agent-supplied feedback for a previously-returned node_id.

    Unlike ``record_used`` (called heuristically from the learning loop) and
    ``mark_ignored_since_injection`` (a batch sweep over every neuron), this is
    the only path where the agent itself says "this was right" or "this was
    wrong" about a specific recall/context_pack/traverse hit. ``"used"`` maps
    to the existing ``record_used`` counter; ``"wrong"`` bumps ``ignored_count``
    immediately instead of waiting for the next batch sweep to infer it from
    injected-without-used timing. ``"not_used"`` is accepted as a neutral
    no-op (the agent looked at it but it wasn't relevant, not actively wrong)
    so callers don't have to pick between "used" and "wrong" when neither fits.

    Returns the node_ids actually updated (empty if the table isn't migrated
    yet or no valid ids were given).
    """
    if not node_ids or not _table_ready(conn):
        return []
    if signal == "used":
        record_used(conn, node_ids)
        return list(node_ids)
    if signal == "not_used":
        return []
    if signal != "wrong":
        msg = f"unknown feedback signal: {signal!r}"
        raise ValueError(msg)

    now = _now()
    updated: list[str] = []
    for node_id in node_ids:
        if not node_id:
            continue
        _ensure_row(conn, node_id)
        conn.execute(
            """
            UPDATE neuron_feedback
            SET ignored_count = ignored_count + 1,
                last_ignored = ?,
                updated_at = ?
            WHERE node_id = ?
            """,
            (now, now, node_id),
        )
        updated.append(node_id)
    return updated


def mark_ignored_since_injection(
    conn: sqlite3.Connection,
    *,
    session_id: str | None = None,
) -> int:
    """Increase ignored_count for neurons injected but never used.

    Uses last_injected vs last_used. Stamps last_ignored. Returns rows updated.
    """
    _ = session_id
    if not _table_ready(conn):
        return 0
    now = _now()
    # Prefer last_ignored column when present (post-010).
    try:
        cur = conn.execute(
            """
            UPDATE neuron_feedback
            SET ignored_count = ignored_count + 1,
                last_ignored = ?,
                updated_at = ?
            WHERE injected_count > used_count
              AND (last_used IS NULL OR last_used < last_injected)
            """,
            (now, now),
        )
    except sqlite3.OperationalError:
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


def _parse_ts(value: str | None) -> datetime | None:
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


def ignore_rate(
    conn: sqlite3.Connection,
    node_id: str,
    *,
    half_life_days: int = 60,
) -> tuple[float, int]:
    """Return (effective_ignore_rate, injected_count).

    effective_ignored = ignored * (0.5 ** (days_since_last_ignore / half_life)).
    If ignored_count==0 or last_ignored IS NULL → effective_ignored=0.
    Scalar last_ignored is a known approximation (not per-event decay).
    """
    if not _table_ready(conn):
        return 0.0, 0
    row = conn.execute(
        """
        SELECT injected_count, ignored_count, last_ignored
        FROM neuron_feedback WHERE node_id = ?
        """,
        (node_id,),
    ).fetchone()
    if row is None:
        return 0.0, 0
    injected = int(row[0] or 0)
    ignored = int(row[1] or 0)
    last_ignored = row[2] if len(row) > 2 else None
    if ignored <= 0 or last_ignored is None:
        return 0.0, injected
    stamp = _parse_ts(str(last_ignored) if last_ignored else None)
    if stamp is None:
        return 0.0, injected
    age_days = max(0.0, (datetime.now(UTC) - stamp).total_seconds() / 86400.0)
    effective_ignored = ignored * (0.5 ** (age_days / float(half_life_days)))
    rate = effective_ignored / max(1, injected)
    return float(rate), injected
