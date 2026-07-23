"""Map retrieval strength to a coarse agent-facing confidence label."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

Confidence = Literal["high", "medium", "low"]


def score_confidence(
    *,
    abstained: bool = False,
    top_score: float | None = None,
    result_count: int = 0,
    min_bm25_strength: float | None = 3.0,
) -> Confidence:
    """Derive high|medium|low from abstention and a BM25 magnitude score.

    ``top_score`` must be a raw FTS5 BM25 value (more negative = stronger).
    Do not pass PPR/activation composite scores — those live in a different domain.
    """
    if abstained or result_count <= 0 or top_score is None:
        return "low"
    floor = float(min_bm25_strength or 3.0)
    strength = abs(float(top_score))
    if strength >= max(floor * 3.0, 12.0):
        return "high"
    if strength >= floor:
        return "medium"
    return "low"


def confidence_for_top_result(
    *,
    abstained: bool,
    result_count: int,
    top_node_id: str | None,
    fts_bm25_by_id: Mapping[str, float],
    min_bm25_strength: float | None = 3.0,
) -> Confidence:
    """Label trust for the top *surfaced* node from its direct FTS BM25.

    Graph-only promotes (no direct FTS hit) stay ``low`` — do not inherit the
    seed-pool's best BM25.
    """
    if abstained or result_count <= 0 or not top_node_id:
        return "low"
    direct = fts_bm25_by_id.get(top_node_id)
    if direct is None:
        return "low"
    return score_confidence(
        abstained=False,
        top_score=direct,
        result_count=result_count,
        min_bm25_strength=min_bm25_strength,
    )


def pack_confidence(
    *,
    kept_count: int = 0,
    top_score: float | None = None,
    top_node_id: str | None = None,
    fts_bm25_by_id: Mapping[str, float] | None = None,
    min_bm25_strength: float | None = 3.0,
    abstained: bool = False,
    graph_only_explicit_seeds: bool = False,
) -> Confidence:
    """Derive pack confidence from retrieval strength (not item density).

    Prefer BM25 of the top included memory. Graph-only packs with explicit
    ``seed_refs`` may be ``medium``; procedures alone never raise confidence.
    """
    if fts_bm25_by_id is not None and top_node_id:
        return confidence_for_top_result(
            abstained=abstained,
            result_count=max(kept_count, 1),
            top_node_id=top_node_id,
            fts_bm25_by_id=fts_bm25_by_id,
            min_bm25_strength=min_bm25_strength,
        )
    if top_score is not None:
        return score_confidence(
            abstained=abstained,
            top_score=top_score,
            result_count=max(kept_count, 1),
            min_bm25_strength=min_bm25_strength,
        )
    if graph_only_explicit_seeds and kept_count > 0:
        return "medium"
    return "low"
