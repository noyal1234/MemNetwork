"""Shared MCP response shaping — neuron conversion, budget trim, hit filtering."""

from __future__ import annotations

import sqlite3

from brainkm.models.schemas import NeuronResult, SessionChunkResult
from brainkm.services.memory import token_count
from brainkm.services.search import RankedNode


def ranked_to_neuron(conn: sqlite3.Connection, ranked: RankedNode) -> NeuronResult | None:
    row = conn.execute(
        """
        SELECT id, kind, subtype, title, content, path
        FROM nodes WHERE id = ? AND valid_until IS NULL
        """,
        (ranked.node_id,),
    ).fetchone()
    if row is None:
        return None
    return NeuronResult(
        node_id=row["id"],
        kind=row["kind"],
        subtype=row["subtype"],
        title=row["title"],
        content=row["content"],
        score=ranked.score,
        activation=ranked.activation,
        path=row["path"] or ranked.path,
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
        excerpt = (
            (chunk.content[:240] + "…") if len(chunk.content) > 240 else chunk.content
        )
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
