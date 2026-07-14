"""Graph traversal and FTS-backed seeding for recall."""

from __future__ import annotations

import re
import sqlite3
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from brainkm.models.brain_config import GraphConfig, RecallConfig
from brainkm.services.abstention import should_abstain_for_query

TYPE_MULTIPLIERS: dict[tuple[str, str | None], float] = {
    ("memory", "decision"): 2.0,
    ("memory", "rule"): 1.8,
    ("memory", "fact"): 1.0,
    ("memory", "error"): 1.5,
    ("memory", "pattern"): 1.2,
    ("memory", "context"): 0.9,
    ("procedure", None): 1.6,
    ("procedure", "workflow"): 1.7,
    ("code", "file"): 0.8,
    ("code", "function"): 0.85,
    ("code", "class"): 0.85,
    ("tool", None): 1.0,
    ("session", None): 0.7,
}

DEFAULT_MULTIPLIER = 1.0

_FTS_TOKEN = re.compile(r"[\w.-]+", re.UNICODE)


def sanitize_fts_query(query: str) -> str:
    """Normalize user text into a safe FTS5 MATCH expression."""
    tokens = _FTS_TOKEN.findall(query)
    if not tokens:
        return '""'
    return " OR ".join(f'"{token}"' for token in tokens[:20])


def fts_search_nodes(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 20,
) -> list[tuple[str, float]]:
    """Return (node_id, bm25_score) pairs from nodes_fts."""
    match_query = sanitize_fts_query(query)
    rows = conn.execute(
        """
        SELECT n.id, bm25(nodes_fts) AS score
        FROM nodes_fts
        JOIN nodes n ON n.rowid = nodes_fts.rowid
        WHERE nodes_fts MATCH ?
          AND (n.valid_until IS NULL)
        ORDER BY score
        LIMIT ?
        """,
        (match_query, limit),
    ).fetchall()
    return [(row[0], float(row[1])) for row in rows]


@dataclass(frozen=True)
class RankedNode:
    node_id: str
    activation: float
    score: float
    kind: str
    subtype: str | None
    title: str
    path: str | None = None
    relationship: str | None = None
    via: str | None = None


@dataclass(frozen=True)
class TraversalResult:
    nodes: list[RankedNode]
    hops_explored: int
    abstained: bool = False


@dataclass
class _ActivationMeta:
    activation: float
    depth: int
    via: str | None = None
    relationship: str | None = None


def type_multiplier(kind: str, subtype: str | None) -> float:
    if (kind, subtype) in TYPE_MULTIPLIERS:
        return TYPE_MULTIPLIERS[(kind, subtype)]
    return TYPE_MULTIPLIERS.get((kind, None), DEFAULT_MULTIPLIER)


def _neighbors_for_node(
    conn: sqlite3.Connection,
    node_id: str,
    *,
    min_weight: float,
    relationship: str | None,
    direction: Literal["out", "in", "both"],
) -> list[tuple[str, float, str]]:
    """Load edges for a single node (indexed lookups)."""
    neighbors: list[tuple[str, float, str]] = []
    if direction in ("out", "both"):
        if relationship:
            rows = conn.execute(
                """
                SELECT to_id, weight, relationship
                FROM edges
                WHERE from_id = ? AND weight >= ? AND relationship = ?
                ORDER BY weight DESC
                """,
                (node_id, min_weight, relationship),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT to_id, weight, relationship
                FROM edges
                WHERE from_id = ? AND weight >= ?
                ORDER BY weight DESC
                """,
                (node_id, min_weight),
            ).fetchall()
        neighbors.extend((row[0], float(row[1]), row[2]) for row in rows)
    if direction in ("in", "both"):
        if relationship:
            rows = conn.execute(
                """
                SELECT from_id, weight, relationship
                FROM edges
                WHERE to_id = ? AND weight >= ? AND relationship = ?
                ORDER BY weight DESC
                """,
                (node_id, min_weight, relationship),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT from_id, weight, relationship
                FROM edges
                WHERE to_id = ? AND weight >= ?
                ORDER BY weight DESC
                """,
                (node_id, min_weight),
            ).fetchall()
        neighbors.extend((row[0], float(row[1]), row[2]) for row in rows)
    return neighbors


def bfs_activate(
    conn: sqlite3.Connection,
    seed_activations: dict[str, float],
    *,
    max_hops: int,
    max_fanout_per_hop: int,
    max_activation_nodes: int,
    min_weight: float,
    direction: Literal["out", "in", "both"] = "both",
    relationship: str | None = None,
) -> tuple[dict[str, _ActivationMeta], int]:
    """Weighted multi-hop BFS from seeded node activations using per-node edge queries."""
    meta: dict[str, _ActivationMeta] = {
        node_id: _ActivationMeta(activation=act, depth=0)
        for node_id, act in seed_activations.items()
    }
    frontier: deque[tuple[str, int]] = deque((node_id, 0) for node_id in seed_activations)
    max_depth_seen = 0

    while frontier and len(meta) < max_activation_nodes:
        node_id, depth = frontier.popleft()
        max_depth_seen = max(max_depth_seen, depth)
        if depth >= max_hops:
            continue

        neighbors = _neighbors_for_node(
            conn,
            node_id,
            min_weight=min_weight,
            relationship=relationship,
            direction=direction,
        )
        neighbors.sort(key=lambda item: item[1], reverse=True)
        for neighbor_id, edge_weight, rel in neighbors[:max_fanout_per_hop]:
            if len(meta) >= max_activation_nodes and neighbor_id not in meta:
                break

            parent_activation = meta[node_id].activation
            propagated = parent_activation * edge_weight
            existing = meta.get(neighbor_id)
            if existing is not None and propagated <= existing.activation:
                continue

            meta[neighbor_id] = _ActivationMeta(
                activation=propagated,
                depth=depth + 1,
                via=node_id,
                relationship=rel,
            )
            frontier.append((neighbor_id, depth + 1))
            max_depth_seen = max(max_depth_seen, depth + 1)

    return meta, max_depth_seen


def rank_activated_nodes(
    conn: sqlite3.Connection,
    activations: dict[str, _ActivationMeta],
) -> list[RankedNode]:
    if not activations:
        return []

    placeholders = ",".join("?" for _ in activations)
    rows = conn.execute(
        f"""
        SELECT id, kind, subtype, title, confidence, path
        FROM nodes
        WHERE id IN ({placeholders})
          AND (valid_until IS NULL)
        """,
        tuple(activations.keys()),
    ).fetchall()

    ranked: list[RankedNode] = []
    for node_id, kind, subtype, title, confidence, path in rows:
        info = activations[node_id]
        multiplier = type_multiplier(kind, subtype)
        score = info.activation * float(confidence) * multiplier
        ranked.append(
            RankedNode(
                node_id=node_id,
                activation=info.activation,
                score=score,
                kind=kind,
                subtype=subtype,
                title=title,
                path=path,
                relationship=info.relationship,
                via=info.via,
            )
        )

    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked


def recall_with_bfs(
    conn: sqlite3.Connection,
    query: str,
    *,
    graph: GraphConfig | None = None,
    recall: RecallConfig | None = None,
    fts_limit: int = 20,
    project_dir: Path | None = None,
) -> TraversalResult:
    """Seed from FTS5 BM25, spread via 2-hop BFS, return ranked nodes."""
    graph_cfg = graph or GraphConfig()
    recall_cfg = recall or RecallConfig()
    seeds = fts_search_nodes(conn, query, limit=fts_limit)
    seed_scores = [score for _, score in seeds]

    if should_abstain_for_query(
        conn,
        seed_scores,
        recall_cfg,
        project_dir=project_dir,
    ):
        return TraversalResult(nodes=[], hops_explored=0, abstained=True)

    if not seeds:
        return TraversalResult(nodes=[], hops_explored=0, abstained=False)

    # BM25 scores are negative; map to positive seed activations.
    seed_activations = {node_id: max(0.1, abs(score)) for node_id, score in seeds}

    activations, hops = bfs_activate(
        conn,
        seed_activations,
        max_hops=2,
        max_fanout_per_hop=graph_cfg.max_bfs_fanout_per_hop,
        max_activation_nodes=graph_cfg.max_activation_nodes,
        min_weight=graph_cfg.min_edge_weight_to_traverse,
        direction="both",
    )
    ranked = rank_activated_nodes(conn, activations)
    return TraversalResult(nodes=ranked, hops_explored=hops, abstained=False)


def resolve_node_ref(conn: sqlite3.Connection, ref: str) -> str | None:
    """Resolve a node ID, path, or title fragment to a node id."""
    by_id = conn.execute(
        "SELECT id FROM nodes WHERE id = ? AND valid_until IS NULL",
        (ref,),
    ).fetchone()
    if by_id:
        return by_id[0]

    by_path = conn.execute(
        "SELECT id FROM nodes WHERE path = ? AND valid_until IS NULL LIMIT 1",
        (ref,),
    ).fetchone()
    if by_path:
        return by_path[0]

    hits = fts_search_nodes(conn, ref, limit=1)
    return hits[0][0] if hits else None


def traverse(
    conn: sqlite3.Connection,
    from_ref: str,
    *,
    to_ref: str | None = None,
    max_hops: int = 1,
    relationship: str | None = None,
    direction: Literal["out", "in", "both"] = "out",
    graph: GraphConfig | None = None,
) -> TraversalResult:
    """Explicit graph hop from a resolved reference."""
    cfg = graph or GraphConfig()
    max_hops = min(max(max_hops, 1), 2)

    start_id = resolve_node_ref(conn, from_ref)
    if start_id is None:
        return TraversalResult(nodes=[], hops_explored=0)

    seed_activations = {start_id: 1.0}
    activations, hops = bfs_activate(
        conn,
        seed_activations,
        max_hops=max_hops,
        max_fanout_per_hop=cfg.max_bfs_fanout_per_hop,
        max_activation_nodes=cfg.max_activation_nodes,
        min_weight=cfg.min_edge_weight_to_traverse,
        direction=direction,
        relationship=relationship,
    )

    if to_ref is not None:
        target_id = resolve_node_ref(conn, to_ref)
        if target_id is None or target_id not in activations:
            return TraversalResult(nodes=[], hops_explored=hops)
        activations = {target_id: activations[target_id]}

    ranked = rank_activated_nodes(conn, activations)
    return TraversalResult(nodes=ranked, hops_explored=hops)
