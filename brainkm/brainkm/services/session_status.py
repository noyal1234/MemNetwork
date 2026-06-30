"""Session context neuron — read/write subtype=context memory."""

from __future__ import annotations

import sqlite3

from brainkm.adapters.redaction import require_clean
from brainkm.services.memory import NeuronRecord, remember_neuron


def _latest_context(conn: sqlite3.Connection, session_id: str | None) -> NeuronRecord | None:
    params: list[object] = []
    session_clause = ""
    if session_id:
        session_clause = "AND session_id = ?"
        params.append(session_id)

    row = conn.execute(
        f"""
        SELECT id, kind, subtype, title, content, valid_from, valid_until, session_id
        FROM nodes
        WHERE valid_until IS NULL
          AND kind = 'memory'
          AND subtype = 'context'
          {session_clause}
        ORDER BY created_at DESC
        LIMIT 1
        """,
        params,
    ).fetchone()
    if row is None:
        return None
    return NeuronRecord(
        id=row["id"],
        kind=row["kind"],
        subtype=row["subtype"],
        title=row["title"],
        content=row["content"],
        valid_from=row["valid_from"],
        valid_until=row["valid_until"],
        session_id=row["session_id"],
    )


def get_session_status(
    conn: sqlite3.Connection,
    *,
    session_id: str | None = None,
) -> NeuronRecord | None:
    return _latest_context(conn, session_id)


def set_session_status(
    conn: sqlite3.Connection,
    *,
    title: str,
    body: str,
    session_id: str | None = None,
) -> NeuronRecord:
    cleaned = require_clean(title, body, source="session_status")
    return remember_neuron(
        conn,
        title=cleaned.title,
        content=cleaned.content,
        kind="memory",
        subtype="context",
        tags=["session_status"],
        session_id=session_id,
        source="session_status",
    )
