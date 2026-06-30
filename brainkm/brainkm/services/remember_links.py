"""Auto-link remember neurons to code nodes and detect supersede candidates."""

from __future__ import annotations

import re
import sqlite3

from brainkm.services.memory import new_ulid
from brainkm.services.search import fts_search_nodes

_PATH_PATTERN = re.compile(
    r"(?:^|[\s\"'`(])"
    r"((?:[\w.-]+/)+[\w.-]+\.(?:py|ts|tsx|js|jsx|go|rs|java|md|json|yaml|yml|toml))"
    r"(?:$|[\s\"'`),:;])",
    re.MULTILINE,
)


def extract_path_mentions(text: str) -> list[str]:
    seen: set[str] = set()
    paths: list[str] = []
    for match in _PATH_PATTERN.finditer(text):
        path = match.group(1).strip()
        if path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def link_code_nodes_by_path(
    conn: sqlite3.Connection,
    neuron_id: str,
    *,
    title: str,
    content: str,
) -> list[str]:
    """Create relates_to edges from neuron to code nodes matching path mentions."""
    linked: list[str] = []
    blob = f"{title}\n{content}"
    for path in extract_path_mentions(blob):
        row = conn.execute(
            """
            SELECT id FROM nodes
            WHERE kind = 'code' AND path = ? AND valid_until IS NULL
            LIMIT 1
            """,
            (path,),
        ).fetchone()
        if row is None:
            continue
        code_id = row[0]
        edge_id = new_ulid()
        now_row = conn.execute("SELECT datetime('now')").fetchone()
        now = now_row[0] if now_row else "now"
        conn.execute(
            """
            INSERT OR IGNORE INTO edges (id, from_id, to_id, relationship, weight, created_at, updated_at)
            VALUES (?, ?, ?, 'relates_to', 0.8, ?, ?)
            """,
            (edge_id, neuron_id, code_id, now, now),
        )
        linked.append(code_id)
    return linked


def find_supersede_candidates(
    conn: sqlite3.Connection,
    *,
    title: str,
    content: str,
    exclude_id: str | None = None,
    similarity_threshold: float = 0.85,
) -> list[str]:
    """Lexical FTS similarity — suggest nodes that may be superseded."""
    query = title.strip()
    if not query:
        return []

    hits = fts_search_nodes(conn, query, limit=5)
    if not hits:
        return []

    best_score = min(score for _, score in hits)
    candidates: list[str] = []
    for node_id, score in hits:
        if exclude_id and node_id == exclude_id:
            continue
        if abs(score) >= abs(best_score) * similarity_threshold:
            candidates.append(node_id)
    return candidates
