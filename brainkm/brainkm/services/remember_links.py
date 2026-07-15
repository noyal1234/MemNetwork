"""Conflict-aware supersede candidate detection for remember."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from brainkm.adapters.embeddings import cosine_similarity, get_embedder
from brainkm.services.memory import new_ulid
from brainkm.services.search import fts_search_nodes

_PATH_PATTERN = re.compile(
    r"(?:^|[\s\"'`(])"
    r"((?:[\w.-]+/)+[\w.-]+\.(?:py|ts|tsx|js|jsx|go|rs|java|md|json|yaml|yml|toml))"
    r"(?:$|[\s\"'`),:;])",
    re.MULTILINE,
)

_NEGATION = re.compile(
    r"\b(not|never|instead of|rather than|no longer|deprecated|reject|avoid|don't|do not)\b",
    re.I,
)


@dataclass(frozen=True)
class SupersedeSuggestion:
    node_id: str
    similarity: float
    conflict: bool
    reason: str


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
    """Backward-compatible list of candidate node ids."""
    return [
        item.node_id
        for item in detect_conflicts(
            conn,
            title=title,
            content=content,
            exclude_id=exclude_id,
            similarity_threshold=similarity_threshold,
        )
    ]


def detect_conflicts(
    conn: sqlite3.Connection,
    *,
    title: str,
    content: str,
    exclude_id: str | None = None,
    similarity_threshold: float = 0.85,
) -> list[SupersedeSuggestion]:
    """High similarity + conflicting claim → supersede suggestion."""
    query = title.strip()
    if not query:
        return []

    hits = fts_search_nodes(conn, query, limit=8)
    if not hits:
        return []

    best_score = min(score for _, score in hits)
    new_blob = f"{title}\n{content}"
    new_neg = bool(_NEGATION.search(new_blob))
    embedder = get_embedder(prefer_onnx=False)
    new_vec = embedder.embed(new_blob)

    suggestions: list[SupersedeSuggestion] = []
    for node_id, score in hits:
        if exclude_id and node_id == exclude_id:
            continue
        relative = abs(score) / max(abs(best_score), 1e-9)
        row = conn.execute(
            "SELECT title, content FROM nodes WHERE id = ? AND valid_until IS NULL",
            (node_id,),
        ).fetchone()
        if row is None:
            continue
        old_blob = f"{row[0]}\n{row[1] or ''}"
        old_vec = embedder.embed(old_blob)
        emb_sim = cosine_similarity(new_vec, old_vec)
        lexical_ok = relative >= similarity_threshold
        semantic_ok = emb_sim >= 0.82
        if not (lexical_ok or semantic_ok):
            continue
        old_neg = bool(_NEGATION.search(old_blob))
        conflict = (new_neg != old_neg) or (
            semantic_ok and emb_sim < 0.97 and new_blob.strip().lower() != old_blob.strip().lower()
        )
        reason = "conflicting claim" if conflict else "near-duplicate"
        suggestions.append(
            SupersedeSuggestion(
                node_id=node_id,
                similarity=max(relative, emb_sim),
                conflict=conflict,
                reason=reason,
            )
        )

    suggestions.sort(key=lambda item: (item.conflict, item.similarity), reverse=True)
    return suggestions
