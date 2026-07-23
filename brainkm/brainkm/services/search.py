"""Graph traversal and hybrid FTS/vector seeding for recall."""

from __future__ import annotations

import math
import re
import sqlite3
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from brainkm.models.brain_config import GraphConfig, RecallConfig, SemanticConfig
from brainkm.models.schemas import ImpactSummary
from brainkm.services.abstention import should_abstain_for_query
from brainkm.services.intent import route_query
from brainkm.services.semantic import reciprocal_rank_fusion, vector_search_nodes

TYPE_MULTIPLIERS: dict[tuple[str, str | None], float] = {
    ("memory", "decision"): 2.0,
    ("memory", "rule"): 1.8,
    ("memory", "fact"): 1.0,
    ("memory", "error"): 1.5,
    ("memory", "pattern"): 1.2,
    ("memory", "context"): 0.9,
    ("memory", "observation"): 0.4,
    ("memory", "episode"): 0.75,
    ("procedure", None): 1.6,
    ("procedure", "workflow"): 1.7,
    ("procedure", "tool_chain"): 1.6,
    ("code", "file"): 0.8,
    ("code", "function"): 0.85,
    ("code", "class"): 0.85,
    ("concept", None): 1.1,
    ("concept", "tag"): 1.1,
    ("tool", None): 1.0,
    ("session", None): 0.7,
}

DEFAULT_MULTIPLIER = 1.0

# Structural edges for traverse (excludes noisy references / co_activated by default).
FLOW_RELATIONSHIPS = frozenset(
    {
        "calls",
        "imports",
        "imports_from",
        "defines",
        "contains",
        "method",
        "uses",
        "inherits",
    }
)

# Default expand allowlist for recall PPR/BFS (typed nodal neighborhood).
EXPAND_RELATIONSHIPS = frozenset(
    {
        "about_file",
        "about_symbol",
        "mentions_concept",
        "implements_concept",
        "supersedes",
        "calls",
        "imports",
        "imports_from",
        "defines",
        "contains",
        "method",
        "uses",
        "inherits",
        "co_activated",
        "spawned",
        "distilled_from",
        "relates_to",
    }
)

UNRESOLVED_TRAVERSE_HINT = (
    "No graph node matched from_ref — pass an exact symbol or file path "
    "(e.g. handle_traverse or brainkm/tools/dispatch.py). "
    "If the graph looks stale, check brain_stats; sync refreshes automatically "
    "or run `brainkm graph sync`."
)

_FTS_TOKEN = re.compile(r"[\w.-]+", re.UNICODE)
_TOKEN_BOUNDARY = re.compile(r"[\w.-]+", re.UNICODE)


def query_tokens(query: str) -> list[str]:
    """Lowercased word tokens from a user query."""
    return [token.lower() for token in _TOKEN_BOUNDARY.findall(query)]


def count_token_overlap(query_tokens_list: list[str], text: str) -> int:
    """Count query tokens that appear in ``text`` (word boundary or substring for longer tokens)."""
    if not query_tokens_list:
        return 0
    lower = text.lower()
    hits = 0
    for token in query_tokens_list:
        if re.search(rf"\b{re.escape(token)}\b", lower):
            hits += 1
        elif len(token) >= 4 and token in lower:
            hits += 1
    return hits


def filter_fts_hits_by_overlap(
    conn: sqlite3.Connection,
    hits: list[tuple[str, float]],
    query: str,
    *,
    min_overlap: int = 2,
) -> list[tuple[str, float]]:
    """Drop weak OR-FTS hits that share fewer than ``min_overlap`` query tokens."""
    tokens = query_tokens(query)
    if len(tokens) < min_overlap:
        return hits
    filtered: list[tuple[str, float]] = []
    for node_id, score in hits:
        row = conn.execute(
            "SELECT title, content FROM nodes WHERE id = ? AND valid_until IS NULL",
            (node_id,),
        ).fetchone()
        if row is None:
            continue
        text = f"{row[0] or ''} {row[1] or ''}"
        if count_token_overlap(tokens, text) >= min_overlap:
            filtered.append((node_id, score))
    return filtered


def parse_relationships(relationship: str | None) -> frozenset[str] | None:
    """Parse a single relationship or comma-separated list. ``*`` means no filter."""
    if relationship is None:
        return None
    text = relationship.strip()
    if not text:
        return None
    if text == "*":
        return None
    parts = frozenset(part.strip() for part in text.split(",") if part.strip())
    return parts or None


def relationships_for_traverse(relationship: str | None) -> frozenset[str] | None:
    """Default to structural flow edges; ``*`` disables the filter."""
    if relationship is None:
        return FLOW_RELATIONSHIPS
    return parse_relationships(relationship)


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
    exclude_kinds: frozenset[str] | None = None,
) -> list[tuple[str, float]]:
    """Return (node_id, bm25_score) pairs from nodes_fts.

    SQLite FTS5 ``bm25()`` is more-negative-better; callers gate on magnitude.
    """
    match_query = sanitize_fts_query(query)
    excluded = exclude_kinds or frozenset()
    if excluded:
        placeholders = ",".join("?" for _ in excluded)
        rows = conn.execute(
            f"""
            SELECT n.id, bm25(nodes_fts) AS score
            FROM nodes_fts
            JOIN nodes n ON n.rowid = nodes_fts.rowid
            WHERE nodes_fts MATCH ?
              AND (n.valid_until IS NULL)
              AND n.kind NOT IN ({placeholders})
            ORDER BY score
            LIMIT ?
            """,
            (match_query, *sorted(excluded), limit),
        ).fetchall()
    else:
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
    hits = [(row[0], float(row[1])) for row in rows]
    return filter_fts_hits_by_overlap(conn, hits, query)


# Concept stubs are indexing glue — exclude from recall/context_pack seeds.
_RECALL_SEED_EXCLUDE_KINDS = frozenset({"concept"})


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
    session_id: str | None = None


@dataclass(frozen=True)
class TraversalResult:
    nodes: list[RankedNode]
    hops_explored: int
    abstained: bool = False
    intent: str | None = None
    resolved_id: str | None = None
    hint: str | None = None
    impact_summary: ImpactSummary | None = None
    fts_bm25_by_id: dict[str, float] = field(default_factory=dict)
    candidates: list[dict[str, str]] = field(default_factory=list)
    abstain_reason: str | None = None  # "unresolved" | "ambiguous" | None


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
    relationships: frozenset[str] | None,
    direction: Literal["out", "in", "both"],
) -> list[tuple[str, float, str]]:
    """Load edges for a single node (indexed lookups)."""
    neighbors: list[tuple[str, float, str]] = []
    rel_sql = ""
    rel_params: tuple[object, ...] = ()
    if relationships:
        placeholders = ",".join("?" for _ in relationships)
        rel_sql = f" AND relationship IN ({placeholders})"
        rel_params = tuple(sorted(relationships))

    if direction in ("out", "both"):
        rows = conn.execute(
            f"""
            SELECT to_id, weight, relationship
            FROM edges
            WHERE from_id = ? AND weight >= ?{rel_sql}
            ORDER BY weight DESC
            """,
            (node_id, min_weight, *rel_params),
        ).fetchall()
        neighbors.extend((row[0], float(row[1]), row[2]) for row in rows)
    if direction in ("in", "both"):
        rows = conn.execute(
            f"""
            SELECT from_id, weight, relationship
            FROM edges
            WHERE to_id = ? AND weight >= ?{rel_sql}
            ORDER BY weight DESC
            """,
            (node_id, min_weight, *rel_params),
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
    relationships: frozenset[str] | None = None,
) -> tuple[dict[str, _ActivationMeta], int]:
    """Weighted multi-hop BFS from seeded node activations using per-node edge queries."""
    rels = relationships if relationships is not None else parse_relationships(relationship)
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
            relationships=rels,
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
    relationships: frozenset[str] | None = None,
) -> tuple[dict[str, _ActivationMeta], int]:
    """Personalized PageRank seeded from retrieval hits; uses edge weights (incl. co_activated)."""
    if not seed_activations:
        return {}, 0

    rels = relationships if relationships is not None else parse_relationships(relationship)
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
                relationships=rels,
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
            relationships=rels,
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
        new_scores = {
            node_id: (1.0 - damping) * personal.get(node_id, 0.0) for node_id in candidate
        }
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
        SELECT id, kind, subtype, title, content, confidence, path, use_count, updated_at,
            session_id
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
        session_id,
    ) in rows:
        info = activations[node_id]
        multiplier = type_multiplier(kind, subtype)
        if subtype in boost_subtypes:
            multiplier *= 1.35
        # Prefer semantic memory over raw observations/episodes in ranking.
        if kind == "memory" and subtype == "observation":
            multiplier *= 0.45
        elif kind == "memory" and subtype == "episode":
            multiplier *= 0.7
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
                session_id=session_id,
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
    fts = fts_search_nodes(
        conn,
        query,
        limit=fts_limit,
        exclude_kinds=_RECALL_SEED_EXCLUDE_KINDS,
    )
    sem = semantic or SemanticConfig()
    if not sem.enabled or not prefer_vector:
        return [(node_id, max(0.1, abs(score))) for node_id, score in fts]

    vectors = vector_search_nodes(
        conn,
        query,
        limit=sem.vector_limit,
        prefer_onnx=sem.prefer_onnx,
    )
    if not vectors:
        return [(node_id, max(0.1, abs(score))) for node_id, score in fts]

    if getattr(sem, "fusion_mode", "rrf") == "fts_primary":
        # Preserve FTS candidate set; only re-order by vector similarity.
        # Avoids pure-vector noise drowning lexical hits on long chat haystacks.
        vec_scores = {node_id: score for node_id, score in vectors}
        rescored = sorted(
            fts,
            key=lambda item: (vec_scores.get(item[0], -1.0), abs(item[1])),
            reverse=True,
        )
        return [(node_id, max(0.1, abs(score))) for node_id, score in rescored]

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
    extra_seed_ids: list[str] | None = None,
) -> TraversalResult:
    """Seed → Expand (typed) → Diversify pipeline for live recall."""
    from brainkm.services.diversify import diversify_ranked
    from brainkm.services.file_history import seed_ids_for_path
    from brainkm.services.remember_links import extract_path_mentions

    graph_cfg = graph or GraphConfig()
    recall_cfg = recall or RecallConfig()
    semantic_cfg = semantic or SemanticConfig()
    routing = route_query(query)

    # Theme-leak / personal prompts: abstain even when keywords collide with neurons.
    if recall_cfg.abstain_on_low_confidence:
        from brainkm.services.intent import is_off_domain_query

        if is_off_domain_query(query):
            return TraversalResult(
                nodes=[],
                hops_explored=0,
                abstained=True,
                intent=routing.intent.value,
                fts_bm25_by_id={},
            )

    # Abstain / per-result confidence use direct FTS BM25 (concepts excluded from seeds).
    fts_only = fts_search_nodes(
        conn,
        query,
        limit=fts_limit,
        exclude_kinds=_RECALL_SEED_EXCLUDE_KINDS,
    )
    fts_bm25_by_id = {node_id: score for node_id, score in fts_only}

    seeds = hybrid_seed(
        conn,
        query,
        fts_limit=fts_limit,
        semantic=semantic_cfg,
        prefer_vector=routing.prefer_vector or semantic_cfg.enabled,
    )

    # Path / hook seeds (file-centric neighborhood).
    path_seeds: list[str] = []
    for path in extract_path_mentions(query):
        path_seeds.extend(seed_ids_for_path(conn, path, limit=6))
    if extra_seed_ids:
        path_seeds.extend(extra_seed_ids)
    seed_map = {node_id: max(0.1, float(score)) for node_id, score in seeds}
    for sid in path_seeds:
        seed_map.setdefault(sid, 0.85)
    seeds = list(seed_map.items())

    # Abstain on FTS BM25 distribution when available — skip when path seeds rescue.
    seed_scores = [score for _, score in fts_only] if fts_only else [s for _, s in seeds]

    if path_seeds:
        # File-centric seeding is an explicit signal; do not abstain solely on weak BM25.
        pass
    elif should_abstain_for_query(
        conn,
        seed_scores,
        recall_cfg,
        project_dir=project_dir,
    ):
        return TraversalResult(
            nodes=[],
            hops_explored=0,
            abstained=True,
            intent=routing.intent.value,
            fts_bm25_by_id=fts_bm25_by_id,
        )

    if not seeds:
        return TraversalResult(
            nodes=[],
            hops_explored=0,
            abstained=False,
            intent=routing.intent.value,
            fts_bm25_by_id=fts_bm25_by_id,
        )

    seed_activations = {node_id: max(0.1, float(score)) for node_id, score in seeds}
    expand_rels = frozenset(recall_cfg.expand_relationships) or EXPAND_RELATIONSHIPS

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
            relationships=expand_rels,
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
            relationships=expand_rels,
        )

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
        ranked = sorted(
            ranked,
            key=lambda item: (item.score, item.updated_at or ""),
            reverse=True,
        )

    ranked = diversify_ranked(
        ranked,
        max_per_session=recall_cfg.max_per_session,
        max_per_kind=dict(recall_cfg.max_per_kind),
    )

    return TraversalResult(
        nodes=ranked,
        hops_explored=hops,
        abstained=False,
        intent=routing.intent.value,
        fts_bm25_by_id=fts_bm25_by_id,
    )


def resolve_node_ref(conn: sqlite3.Connection, ref: str) -> str | None:
    """Resolve a node ID, path, or title fragment to a node id (best-effort)."""
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


@dataclass(frozen=True)
class TraverseRefResolution:
    """Result of strict traverse from_ref / to_ref resolution."""

    resolved_id: str | None
    hint: str | None = None
    candidates: list[dict[str, str]] = field(default_factory=list)
    abstain_reason: str | None = None  # "unresolved" | "ambiguous"


def resolve_traverse_ref(conn: sqlite3.Connection, ref: str) -> TraverseRefResolution:
    """Resolve traverse refs with abstention on ambiguous FTS matches.

    Exact id or path wins. Otherwise FTS top-3:
    - exact title match (prefer code on collision) resolves;
    - single hit resolves;
    - top BM25 clearly stronger (|top| >= 2×|second| and top > 0) resolves;
    - exact ties / ratio < 2 → abstain as ``ambiguous`` (prefer abstain over
      wrong blast-radius; the 2× floor is a conservative untuned heuristic).

    Candidate labels are outbound-sanitized before inclusion in hints.
    """
    from brainkm.services.outbound import sanitize_untrusted_agent_text

    cleaned = (ref or "").strip()
    if not cleaned:
        return TraverseRefResolution(
            resolved_id=None,
            hint=UNRESOLVED_TRAVERSE_HINT,
            abstain_reason="unresolved",
        )

    by_id = conn.execute(
        "SELECT id FROM nodes WHERE id = ? AND valid_until IS NULL",
        (cleaned,),
    ).fetchone()
    if by_id:
        return TraverseRefResolution(resolved_id=by_id[0])

    by_path = conn.execute(
        "SELECT id, title, path FROM nodes WHERE path = ? AND valid_until IS NULL LIMIT 1",
        (cleaned,),
    ).fetchone()
    if by_path:
        return TraverseRefResolution(resolved_id=by_path[0])

    hits = fts_search_nodes(conn, cleaned, limit=3)
    if not hits:
        return TraverseRefResolution(
            resolved_id=None,
            hint=UNRESOLVED_TRAVERSE_HINT,
            abstain_reason="unresolved",
        )

    def _row(node_id: str):
        return conn.execute(
            "SELECT id, kind, title, path FROM nodes WHERE id = ?",
            (node_id,),
        ).fetchone()

    def _candidate(node_id: str, score: float) -> dict[str, str]:
        row = _row(node_id)
        label = node_id
        if row:
            raw_label = (row["path"] or row["title"] or node_id)[:120]
            label = sanitize_untrusted_agent_text(
                raw_label,
                placeholder="[redacted candidate]",
            )
        return {
            "node_id": node_id,
            "label": label,
            "bm25": f"{score:.3f}",
        }

    # Prefer exact title match among FTS hits (avoids near-zero BM25 ties in
    # tiny corpora where memory bodies also mention the symbol).
    needle = cleaned.casefold()
    exact_title: list[tuple[str, float]] = []
    for nid, sc in hits:
        row = _row(nid)
        if row and (row["title"] or "").casefold() == needle:
            exact_title.append((nid, sc))
    if len(exact_title) == 1:
        return TraverseRefResolution(resolved_id=exact_title[0][0])
    if len(exact_title) > 1:
        # Prefer code nodes on exact title collision.
        code_exact = [
            (nid, sc)
            for nid, sc in exact_title
            if (_row(nid) and _row(nid)["kind"] == "code")
        ]
        if len(code_exact) == 1:
            return TraverseRefResolution(resolved_id=code_exact[0][0])

    if len(hits) == 1:
        return TraverseRefResolution(resolved_id=hits[0][0])

    top_id, top_score = hits[0]
    _second_id, second_score = hits[1]
    top_mag = abs(float(top_score))
    second_mag = abs(float(second_score))
    # Ratio == 1 (exact tie) and ratio < 2 → abstain.
    if top_mag >= max(second_mag * 2.0, second_mag + 1e-9) and top_mag > 0:
        return TraverseRefResolution(resolved_id=top_id)

    candidates = [_candidate(nid, sc) for nid, sc in hits[:3]]
    labels = ", ".join(c["label"] or c["node_id"] for c in candidates)
    hint = (
        f"Ambiguous from_ref matched multiple nodes ({labels}). "
        "Pass an exact node id or file path, or a more specific symbol."
    )
    return TraverseRefResolution(
        resolved_id=None,
        hint=hint,
        candidates=candidates,
        abstain_reason="ambiguous",
    )


def traverse(
    conn: sqlite3.Connection,
    from_ref: str,
    *,
    to_ref: str | None = None,
    max_hops: int = 1,
    relationship: str | None = None,
    direction: Literal["out", "in", "both"] = "both",
    graph: GraphConfig | None = None,
) -> TraversalResult:
    """Explicit graph hop from a resolved reference (structural flow edges by default)."""
    from brainkm.services.impact import compute_impact_summary

    cfg = graph or GraphConfig()
    max_hops = min(max(max_hops, 1), 2)
    rels = relationships_for_traverse(relationship)

    resolved = resolve_traverse_ref(conn, from_ref)
    start_id = resolved.resolved_id
    if start_id is None:
        return TraversalResult(
            nodes=[],
            hops_explored=0,
            resolved_id=None,
            hint=resolved.hint or UNRESOLVED_TRAVERSE_HINT,
            abstained=True,
            candidates=list(resolved.candidates),
            abstain_reason=resolved.abstain_reason or "unresolved",
        )

    seed_activations = {start_id: 1.0}
    activations, hops = bfs_activate(
        conn,
        seed_activations,
        max_hops=max_hops,
        max_fanout_per_hop=cfg.max_bfs_fanout_per_hop,
        max_activation_nodes=cfg.max_activation_nodes,
        min_weight=cfg.min_edge_weight_to_traverse,
        direction=direction,
        relationships=rels,
    )

    if to_ref is not None:
        target = resolve_traverse_ref(conn, to_ref)
        target_id = target.resolved_id
        if target_id is None or target_id not in activations:
            return TraversalResult(
                nodes=[],
                hops_explored=hops,
                resolved_id=start_id,
                abstained=True,
                abstain_reason=(
                    (target.abstain_reason or "unresolved")
                    if target_id is None
                    else "unresolved"
                ),
                candidates=list(target.candidates) if target_id is None else [],
                hint=(
                    target.hint
                    if target_id is None
                    else (
                        f"Resolved {start_id} but to_ref was not reached within "
                        f"{max_hops} hop(s) (direction={direction}). "
                        "Try max_hops=2, direction=both, or relationship=*."
                    )
                ),
            )
        activations = {target_id: activations[target_id]}

    # Drop the seed — agents already know from_ref; neighbors are the answer.
    neighbor_activations = {
        node_id: meta for node_id, meta in activations.items() if node_id != start_id
    }
    ranked = rank_activated_nodes(conn, neighbor_activations)
    impact = compute_impact_summary(
        conn,
        neighbor_activations,
        seed_id=None,
    )
    hint = None
    if not ranked:
        hint = (
            f"Resolved {start_id} but found no neighbors in {hops} hop(s) "
            f"(direction={direction}). Try direction=both, max_hops=2, "
            "or relationship=* to include references/co_activated."
        )
    return TraversalResult(
        nodes=ranked,
        hops_explored=hops,
        resolved_id=start_id,
        hint=hint,
        impact_summary=impact,
    )
