"""Shared MCP response shaping — neuron conversion, budget trim, hit filtering."""

from __future__ import annotations

import sqlite3

from brainkm.models.schemas import NeuronResult, SessionChunkResult
from brainkm.services.memory import token_count
from brainkm.services.remember_links import extract_path_mentions
from brainkm.services.search import RankedNode


def resolve_display_path(
    conn: sqlite3.Connection,
    *,
    node_id: str,
    title: str,
    content: str | None,
    existing_path: str | None,
) -> str | None:
    """Fill a user-facing path with deterministic tie-breaks.

    Order:
    1. Existing ``nodes.path``
    2. Earliest path mention in title+content (``extract_path_mentions`` finditer order)
    3. ``about_file`` target whose path appears earliest in that mention list
    4. Else earliest ``about_file`` by ``edges.rowid``
    """
    if existing_path:
        return existing_path
    blob = f"{title}\n{content or ''}"
    mentions = extract_path_mentions(blob)
    if mentions:
        return mentions[0]

    rows = conn.execute(
        """
        SELECT n.path
        FROM edges e
        JOIN nodes n ON n.id = e.to_id
        WHERE e.from_id = ?
          AND e.relationship = 'about_file'
          AND n.path IS NOT NULL
          AND n.path != ''
          AND (n.valid_until IS NULL)
        ORDER BY e.rowid ASC
        """,
        (node_id,),
    ).fetchall()
    about_paths = [row[0] for row in rows if row[0]]
    if not about_paths:
        return None
    return about_paths[0]


def ranked_to_neuron(conn: sqlite3.Connection, ranked: RankedNode) -> NeuronResult | None:
    from brainkm.services.outbound import filter_outbound_text

    row = conn.execute(
        """
        SELECT id, kind, subtype, title, content, path
        FROM nodes WHERE id = ? AND valid_until IS NULL
        """,
        (ranked.node_id,),
    ).fetchone()
    if row is None:
        return None
    title = row["title"] or ""
    content = row["content"]
    kind = row["kind"]
    # Agent-facing memory/procedure/concept bodies must pass the outbound gate.
    # Code graph nodes keep structural metadata; still strip injection from text.
    if kind in {"memory", "procedure", "concept"}:
        cleaned = filter_outbound_text(title, content, require_noise_gate=True)
        if cleaned is None:
            return None
        title, content = cleaned.title, cleaned.content or None
    elif content:
        cleaned = filter_outbound_text(title, content, require_noise_gate=False)
        if cleaned is None:
            content = None
        else:
            title, content = cleaned.title, cleaned.content or None
    path = resolve_display_path(
        conn,
        node_id=row["id"],
        title=title,
        content=content,
        existing_path=row["path"] or ranked.path,
    )
    return NeuronResult(
        node_id=row["id"],
        kind=kind,
        subtype=row["subtype"],
        title=title,
        content=content,
        score=ranked.score,
        activation=ranked.activation,
        path=path,
        relationship=ranked.relationship,
        via=ranked.via,
    )


def trim_neurons_to_budget(
    nodes: list[NeuronResult],
    *,
    budget: int,
) -> list[NeuronResult]:
    """Keep full neuron bodies until the token budget is exhausted; truncate last if needed."""
    if budget <= 0 or not nodes:
        return []
    kept: list[NeuronResult] = []
    used = 0
    for node in nodes:
        body = node.content or ""
        cost = token_count(f"{node.title}\n{body}")
        if used + cost <= budget:
            kept.append(node)
            used += cost
            continue
        remaining = budget - used
        if remaining < 20:
            break
        lo, hi = 0, len(body)
        best = ""
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = body[:mid]
            if mid < len(body):
                candidate = candidate.rstrip() + "…"
            c = token_count(f"{node.title}\n{candidate}")
            if c <= remaining:
                best = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        kept.append(node.model_copy(update={"content": best or None}))
        break
    return kept


def filter_active_memory_ids(
    conn: sqlite3.Connection,
    hit_ids: list[str],
) -> list[str]:
    """Return active memory neuron IDs from a candidate list (preserves order)."""
    if not hit_ids:
        return []
    placeholders = ",".join("?" * len(hit_ids))
    rows = conn.execute(
        f"""
        SELECT id FROM nodes
        WHERE id IN ({placeholders})
          AND kind = 'memory'
          AND valid_until IS NULL
        """,
        hit_ids,
    ).fetchall()
    active = {row[0] for row in rows}
    return [node_id for node_id in hit_ids if node_id in active]


def budget_session_chunk_excerpts(
    chunks: list,
    *,
    budget: int,
) -> list[SessionChunkResult]:
    """Convert session chunks to budgeted excerpts for recall responses."""
    results: list[SessionChunkResult] = []
    chunk_used = 0
    for chunk in chunks:
        excerpt = (chunk.content[:240] + "…") if len(chunk.content) > 240 else chunk.content
        cost = token_count(excerpt)
        if results and chunk_used + cost > budget:
            break
        if not results and cost > budget:
            while excerpt and token_count(excerpt) > budget:
                excerpt = excerpt[: max(0, len(excerpt) - 20)].rstrip() + "…"
            if not excerpt or token_count(excerpt) > budget:
                break
            cost = token_count(excerpt)
        results.append(
            SessionChunkResult(
                chunk_id=chunk.chunk_id,
                excerpt=excerpt,
                score=chunk.score,
            )
        )
        chunk_used += cost
    return results
