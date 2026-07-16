"""Graph traversal and hybrid FTS/vector seeding for recall."""

from __future__ import annotations

import math
import re
import sqlite3
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from brainkm.models.brain_config import GraphConfig, RecallConfig, SemanticConfig
from brainkm.services.abstention import should_abstain_for_query
from brainkm.services.intent import QueryIntent, route_query
from brainkm.services.semantic import reciprocal_rank_fusion, vector_search_nodes

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
    content: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class TraversalResult:
    nodes: list[RankedNode]
    hops_explored: int
    abstained: bool = False
    intent: str | None = None


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


def ppr_activate(
    conn: sqlite3.Connection,
    seed_activations: dict[str, float],
    *,
    damping: float = 0.85,
    iterations: int = 8,
    max_activation_nodes: int = 500,
    min_weight: float = 0.3,
    direction: Literal["out", "in", "both"] = "both",
    relationship: str | None = None,
) -> tuple[dict[str, _ActivationMeta], int]:
    """Personalized PageRank seeded from retrieval hits; uses edge weights (incl. co_activated)."""
    if not seed_activations:
        return {}, 0

    seed_sum = sum(seed_activations.values()) or 1.0
    personal: dict[str, float] = {k: v / seed_sum for k, v in seed_activations.items()}

    # Build local subgraph via expansion from seeds.
    candidate: set[str] = set(seed_activations)
    frontier = list(seed_activations.keys())
    hop = 0
    while frontier and len(candidate) < max_activation_nodes and hop < 3:
        hop += 1
        nxt: list[str] = []
        for node_id in frontier:
            for neighbor_id, _, _ in _neighbors_for_node(
                conn,
                node_id,
                min_weight=min_weight,
                relationship=relationship,
                direction=direction,
            ):
                if neighbor_id not in candidate and len(candidate) < max_activation_nodes:
                    candidate.add(neighbor_id)
                    nxt.append(neighbor_id)
        frontier = nxt

    adjacency: dict[str, list[tuple[str, float, str]]] = {}
    out_weight: dict[str, float] = defaultdict(float)
    for node_id in candidate:
        neighbors = _neighbors_for_node(
            conn,
            node_id,
            min_weight=min_weight,
            relationship=relationship,
            direction=direction,
        )
        # Prefer higher-weight edges; keep bounded fanout.
        neighbors.sort(key=lambda item: item[1], reverse=True)
        neighbors = neighbors[:50]
        adjacency[node_id] = neighbors
        for neighbor_id, weight, _ in neighbors:
            if neighbor_id in candidate:
                out_weight[node_id] += weight

    scores = {node_id: personal.get(node_id, 0.0) for node_id in candidate}
    for _ in range(iterations):
        new_scores = {node_id: (1.0 - damping) * personal.get(node_id, 0.0) for node_id in candidate}
        for node_id, neighbors in adjacency.items():
            mass = scores.get(node_id, 0.0)
            total_w = out_weight.get(node_id, 0.0)
            if total_w <= 0.0:
                # Dangling: redistribute to personalization.
                for seed_id, p_mass in personal.items():
                    new_scores[seed_id] = new_scores.get(seed_id, 0.0) + damping * mass * p_mass
                continue
            for neighbor_id, weight, _ in neighbors:
                if neighbor_id not in candidate:
                    continue
                new_scores[neighbor_id] = new_scores.get(neighbor_id, 0.0) + (
                    damping * mass * (weight / total_w)
                )
        scores = new_scores

    # via/relationship: strongest incoming from a seed when available.
    via_map: dict[str, tuple[str | None, str | None]] = {s: (None, None) for s in seed_activations}
    for node_id in candidate:
        if node_id in via_map:
            continue
        best: tuple[float, str, str] | None = None
        for other_id in seed_activations:
            for neighbor_id, weight, rel in adjacency.get(other_id, []):
                if neighbor_id == node_id and (best is None or weight > best[0]):
                    best = (weight, other_id, rel)
        if best is not None:
            via_map[node_id] = (best[1], best[2])
        else:
            via_map[node_id] = (None, None)

    meta = {
        node_id: _ActivationMeta(
            activation=max(0.0, act),
            depth=0 if node_id in seed_activations else 1,
            via=via_map.get(node_id, (None, None))[0],
            relationship=via_map.get(node_id, (None, None))[1],
        )
        for node_id, act in scores.items()
        if act > 1e-9
    }
    return meta, hop


def _decay_multiplier(
    updated_at: str | None,
    use_count: int,
    *,
    half_life_days: float,
) -> float:
    """Recency + use_count damping in (0, 1.5]."""
    use_boost = 1.0 + min(0.5, math.log1p(max(0, use_count)) / 10.0)
    if not updated_at or half_life_days <= 0:
        return use_boost
    try:
        # SQLite datetime('now') is naive UTC-ish; accept ISO too.
        ts = updated_at.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(ts)
        except ValueError:
            dt = datetime.strptime(updated_at[:19], "%Y-%m-%d %H:%M:%S")
        age_days = max(
            0.0,
            (datetime.now(tz=None) - dt.replace(tzinfo=None)).total_seconds() / 86400.0,
        )
    except Exception:  # noqa: BLE001
        return use_boost
    recency = 0.5 ** (age_days / half_life_days)
    return use_boost * (0.35 + 0.65 * recency)


def _feedback_multiplier(conn: sqlite3.Connection, node_id: str) -> float:
    row = conn.execute(
        """
        SELECT injected_count, used_count, ignored_count
        FROM neuron_feedback WHERE node_id = ?
        """,
        (node_id,),
    ).fetchone()
    if row is None:
        return 1.0
    injected, used, ignored = int(row[0]), int(row[1]), int(row[2])
    if injected <= 0 and used <= 0:
        return 1.0
    use_rate = used / max(1, injected + used)
    ignore_rate = ignored / max(1, injected + ignored)
    return max(0.4, min(1.8, 1.0 + use_rate - 0.5 * ignore_rate))


def rank_activated_nodes(
    conn: sqlite3.Connection,
    activations: dict[str, _ActivationMeta],
    *,
    boost_subtypes: tuple[str, ...] = (),
    recall: RecallConfig | None = None,
) -> list[RankedNode]:
    if not activations:
        return []

    recall_cfg = recall or RecallConfig()
    placeholders = ",".join("?" for _ in activations)
    rows = conn.execute(
        f"""
        SELECT id, kind, subtype, title, content, confidence, path, use_count, updated_at
        FROM nodes
        WHERE id IN ({placeholders})
          AND (valid_until IS NULL)
        """,
        tuple(activations.keys()),
    ).fetchall()

    has_feedback = (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='neuron_feedback'"
        ).fetchone()
        is not None
    )

    ranked: list[RankedNode] = []
    for (
        node_id,
        kind,
        subtype,
        title,
        content,
        confidence,
        path,
        use_count,
        updated_at,
    ) in rows:
        info = activations[node_id]
        multiplier = type_multiplier(kind, subtype)
        if subtype in boost_subtypes:
            multiplier *= 1.35
        score = info.activation * float(confidence) * multiplier
        score *= _decay_multiplier(
            updated_at,
            int(use_count or 0),
            half_life_days=recall_cfg.decay_half_life_days,
        )
        if recall_cfg.feedback_boost and has_feedback:
            score *= _feedback_multiplier(conn, node_id)
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
                content=content,
                updated_at=updated_at,
            )
        )

    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked


def hybrid_seed(
    conn: sqlite3.Connection,
    query: str,
    *,
    fts_limit: int = 20,
    semantic: SemanticConfig | None = None,
    prefer_vector: bool = True,
) -> list[tuple[str, float]]:
    """FTS seeds fused with vector hits via RRF when semantic is enabled."""
    fts = fts_search_nodes(conn, query, limit=fts_limit)
    sem = semantic or SemanticConfig()
    if not sem.enabled or not prefer_vector:
        return [(node_id, max(0.1, abs(score))) for node_id, score in fts]

    vectors = vector_search_nodes(
        conn,
        query,
        limit=sem.vector_limit,
        prefer_onnx=sem.prefer_onnx,
    )
    # Convert cosine to ranking list (already sorted); FTS uses BM25 order.
    fused = reciprocal_rank_fusion(fts, vectors, k=sem.rrf_k)
    if not fused:
        return [(node_id, max(0.1, abs(score))) for node_id, score in fts]
    return fused


def recall_with_bfs(
    conn: sqlite3.Connection,
    query: str,
    *,
    graph: GraphConfig | None = None,
    recall: RecallConfig | None = None,
    semantic: SemanticConfig | None = None,
    fts_limit: int = 20,
    project_dir: Path | None = None,
) -> TraversalResult:
    """Seed from hybrid retrieval, activate via PPR (default) or BFS, return ranked nodes."""
    graph_cfg = graph or GraphConfig()
    recall_cfg = recall or RecallConfig()
    semantic_cfg = semantic or SemanticConfig()
    routing = route_query(query)

    seeds = hybrid_seed(
        conn,
        query,
        fts_limit=fts_limit,
        semantic=semantic_cfg,
        prefer_vector=routing.prefer_vector or semantic_cfg.enabled,
    )
    # Abstain on FTS BM25 distribution when available.
    fts_only = fts_search_nodes(conn, query, limit=fts_limit)
    seed_scores = [score for _, score in fts_only] if fts_only else [s for _, s in seeds]

    if should_abstain_for_query(
        conn,
        seed_scores,
        recall_cfg,
        project_dir=project_dir,
    ):
        return TraversalResult(
            nodes=[], hops_explored=0, abstained=True, intent=routing.intent.value
        )

    if not seeds:
        return TraversalResult(
            nodes=[], hops_explored=0, abstained=False, intent=routing.intent.value
        )

    seed_activations = {node_id: max(0.1, float(score)) for node_id, score in seeds}

    max_hops = routing.graph_hops if routing.prefer_graph else min(2, routing.graph_hops)
    if recall_cfg.activation == "ppr":
        activations, hops = ppr_activate(
            conn,
            seed_activations,
            damping=recall_cfg.ppr_damping,
            iterations=recall_cfg.ppr_iterations,
            max_activation_nodes=graph_cfg.max_activation_nodes,
            min_weight=graph_cfg.min_edge_weight_to_traverse,
            direction="both",
        )
    else:
        activations, hops = bfs_activate(
            conn,
            seed_activations,
            max_hops=max_hops,
            max_fanout_per_hop=graph_cfg.max_bfs_fanout_per_hop,
            max_activation_nodes=graph_cfg.max_activation_nodes,
            min_weight=graph_cfg.min_edge_weight_to_traverse,
            direction="both",
        )

    # Temporal intent: prefer nodes still valid and recently updated (already in decay).
    ranked = rank_activated_nodes(
        conn,
        activations,
        boost_subtypes=routing.boost_subtypes,
        recall=recall_cfg,
    )

    if recall_cfg.rerank:
        from brainkm.services.rerank import rerank_nodes

        ranked = rerank_nodes(query, ranked, enabled=True)

    if routing.time_filter:
        # Soft temporal preference: keep score primary, prefer fresher ties.
        ranked = sorted(
            ranked,
            key=lambda item: (item.score, item.updated_at or ""),
            reverse=True,
        )

    return TraversalResult(
        nodes=ranked,
        hops_explored=hops,
        abstained=False,
        intent=routing.intent.value,
    )


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
