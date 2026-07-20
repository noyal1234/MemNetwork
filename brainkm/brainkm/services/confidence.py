"""Map retrieval strength to a coarse agent-facing confidence label."""

from __future__ import annotations

from typing import Literal

Confidence = Literal["high", "medium", "low"]


def score_confidence(
    *,
    abstained: bool = False,
    top_score: float | None = None,
    result_count: int = 0,
    min_bm25_strength: float | None = 3.0,
) -> Confidence:
    """Derive high|medium|low from abstention and top BM25/activation score."""
    if abstained or result_count <= 0 or top_score is None:
        return "low"
    floor = float(min_bm25_strength or 3.0)
    strength = abs(float(top_score))
    if strength >= max(floor * 3.0, 12.0):
        return "high"
    if strength >= floor:
        return "medium"
    return "low"


def pack_confidence(kept_count: int) -> Confidence:
    """Derive confidence from context_pack density (included neuron/graph ids)."""
    if kept_count <= 0:
        return "low"
    if kept_count >= 4:
        return "high"
    return "medium"
