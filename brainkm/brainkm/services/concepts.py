"""Deterministic concept materialization from tags and path/symbol tokens."""

from __future__ import annotations

import re
import sqlite3

from brainkm.services.memory import new_ulid, remember_neuron
from brainkm.services.remember_links import extract_path_mentions, extract_symbol_mentions

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_MIN_SLUG_LEN = 3
_STOP = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "this",
        "that",
        "auto",
        "observe",
        "tool",
        "episode",
        "procedure",
        "memory",
        "team",
    }
)


def concept_slug(raw: str) -> str | None:
    slug = _SLUG_RE.sub("-", raw.strip().lower()).strip("-")
    if len(slug) < _MIN_SLUG_LEN or slug in _STOP:
        return None
    if slug.startswith("observe-fp") or slug.startswith("tool-"):
        return None
    return slug[:64]


def concept_node_id(slug: str) -> str:
    return f"concept:{slug}"


def ensure_concept(
    conn: sqlite3.Connection,
    slug: str,
) -> str:
    node_id = concept_node_id(slug)
    row = conn.execute(
        "SELECT id FROM nodes WHERE id = ? AND valid_until IS NULL",
        (node_id,),
    ).fetchone()
    if row:
        return node_id
    remember_neuron(
        conn,
        title=slug.replace("-", " "),
        content=f"Concept: {slug}",
        kind="concept",
        subtype="tag",
        source="concept_materialize",
        confidence=0.7,
        tags=[slug, "concept"],
        node_id=node_id,
        compress=False,
    )
    return node_id


def _insert_edge(
    conn: sqlite3.Connection,
    *,
    from_id: str,
    to_id: str,
    relationship: str,
    weight: float,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO edges (id, from_id, to_id, relationship, weight, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """,
        (new_ulid(), from_id, to_id, relationship, weight),
    )


def materialize_concepts_for_neuron(
    conn: sqlite3.Connection,
    neuron_id: str,
    *,
    title: str,
    content: str,
    tags: list[str] | None = None,
    kind: str = "memory",
) -> list[str]:
    """Upsert concept nodes and link mentions/implements. Returns concept ids."""
    candidates: list[str] = []
    for tag in tags or []:
        slug = concept_slug(tag)
        if slug:
            candidates.append(slug)
    for path in extract_path_mentions(f"{title}\n{content}"):
        base = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        slug = concept_slug(base)
        if slug:
            candidates.append(slug)
    for symbol in extract_symbol_mentions(f"{title}\n{content}"):
        slug = concept_slug(symbol)
        if slug:
            candidates.append(slug)

    seen: set[str] = set()
    concept_ids: list[str] = []
    for slug in candidates:
        if slug in seen:
            continue
        seen.add(slug)
        cid = ensure_concept(conn, slug)
        concept_ids.append(cid)
        if kind == "code":
            _insert_edge(
                conn,
                from_id=neuron_id,
                to_id=cid,
                relationship="implements_concept",
                weight=0.6,
            )
        else:
            _insert_edge(
                conn,
                from_id=neuron_id,
                to_id=cid,
                relationship="mentions_concept",
                weight=0.7,
            )
    return concept_ids
