"""Suppress session_fts chunk hits already covered by chunk_sources neuron hits."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from brainkm.services.search import sanitize_fts_query


@dataclass(frozen=True)
class SessionChunkHit:
    chunk_id: str
    content: str
    score: float


def chunks_covered_by_neurons(
    conn: sqlite3.Connection,
    neuron_ids: set[str],
) -> set[str]:
    if not neuron_ids:
        return set()
    placeholders = ",".join("?" for _ in neuron_ids)
    rows = conn.execute(
        f"""
        SELECT DISTINCT chunk_id
        FROM chunk_sources
        WHERE neuron_id IN ({placeholders})
        """,
        tuple(neuron_ids),
    ).fetchall()
    return {row[0] for row in rows}


def search_session_chunks(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 10,
) -> list[SessionChunkHit]:
    match_query = sanitize_fts_query(query)
    rows = conn.execute(
        """
        SELECT sc.id, sc.content, bm25(session_fts) AS score
        FROM session_fts
        JOIN session_chunks sc ON sc.rowid = session_fts.rowid
        WHERE session_fts MATCH ?
        ORDER BY score
        LIMIT ?
        """,
        (match_query, limit),
    ).fetchall()
    return [
        SessionChunkHit(chunk_id=row[0], content=row[1], score=float(row[2]))
        for row in rows
    ]


def deduped_session_chunks(
    conn: sqlite3.Connection,
    query: str,
    neuron_ids: set[str],
    *,
    limit: int = 5,
) -> list[SessionChunkHit]:
    """Return session chunk hits excluding chunks already linked to recalled neurons."""
    covered = chunks_covered_by_neurons(conn, neuron_ids)
    hits = search_session_chunks(conn, query, limit=limit * 2)
    deduped: list[SessionChunkHit] = []
    for hit in hits:
        if hit.chunk_id in covered:
            continue
        deduped.append(hit)
        if len(deduped) >= limit:
            break
    return deduped
