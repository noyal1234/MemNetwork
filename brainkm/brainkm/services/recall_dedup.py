"""Suppress session_fts chunk hits already covered by chunk_sources neuron hits."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from brainkm.services.search import sanitize_fts_query

# SQLite FTS5 bm25(): more-negative = better match. Gates use abs(score) magnitude only.
_DEFAULT_MIN_BM25 = 3.0
_SHINGLE_N = 8
_JACCARD_NEAR_DUP = 0.5


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
    return [SessionChunkHit(chunk_id=row[0], content=row[1], score=float(row[2])) for row in rows]


def _char_shingles(text: str, *, n: int = _SHINGLE_N) -> set[str]:
    norm = re.sub(r"\s+", " ", (text or "").lower()).strip()
    if not norm:
        return set()
    if len(norm) < n:
        return {norm}
    return {norm[i : i + n] for i in range(len(norm) - n + 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def collapse_near_duplicate_chunks(
    hits: list[SessionChunkHit],
    *,
    threshold: float = _JACCARD_NEAR_DUP,
) -> list[SessionChunkHit]:
    """Drop sliding-window overlaps via character-shingle Jaccard (not prefix)."""
    kept: list[SessionChunkHit] = []
    kept_shingles: list[set[str]] = []
    for hit in hits:
        shingles = _char_shingles(hit.content)
        if any(_jaccard(shingles, prior) >= threshold for prior in kept_shingles):
            continue
        kept.append(hit)
        kept_shingles.append(shingles)
    return kept


def deduped_session_chunks(
    conn: sqlite3.Connection,
    query: str,
    neuron_ids: set[str],
    *,
    limit: int = 5,
    min_bm25_strength: float | None = _DEFAULT_MIN_BM25,
) -> list[SessionChunkHit]:
    """Return session chunk hits excluding covered / weak / near-duplicate rows.

    SQLite FTS5 ``bm25()`` is more-negative-better; weak hits have small
    ``abs(score)`` (near zero). Never filter on sign alone.
    """
    if not neuron_ids:
        return []
    covered = chunks_covered_by_neurons(conn, neuron_ids)
    hits = search_session_chunks(conn, query, limit=max(limit * 4, 10))
    floor = float(min_bm25_strength) if min_bm25_strength is not None else 0.0
    filtered: list[SessionChunkHit] = []
    for hit in hits:
        if hit.chunk_id in covered:
            continue
        # Magnitude gate: more-negative BM25 ⇒ larger abs ⇒ stronger match.
        if floor > 0 and abs(hit.score) < floor:
            continue
        filtered.append(hit)
    collapsed = collapse_near_duplicate_chunks(filtered)
    return collapsed[:limit]
