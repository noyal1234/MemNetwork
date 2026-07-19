"""Information-retrieval ranking metrics for product-grade benches."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


def recall_at_k(
    ranked_ids: Sequence[str],
    relevant_ids: Sequence[str] | set[str],
    k: int,
) -> float:
    """Fraction of relevant docs retrieved in the top-k (0 if no relevants)."""
    if k <= 0:
        return 0.0
    relevant = set(relevant_ids)
    if not relevant:
        return 0.0
    top = list(ranked_ids)[:k]
    hits = sum(1 for doc_id in top if doc_id in relevant)
    return hits / len(relevant)


def precision_at_k(
    ranked_ids: Sequence[str],
    relevant_ids: Sequence[str] | set[str],
    k: int,
) -> float:
    """Fraction of the top-k results that are relevant (0 if k<=0 or empty top)."""
    if k <= 0:
        return 0.0
    relevant = set(relevant_ids)
    top = list(ranked_ids)[:k]
    if not top:
        return 0.0
    hits = sum(1 for doc_id in top if doc_id in relevant)
    return hits / len(top)


def recall_at_budget(
    included_ids: Sequence[str],
    relevant_ids: Sequence[str] | set[str],
) -> float:
    """1.0 if any relevant id appears in the pack's included set (else 0.0).

    Matches ``recall_any@K`` semantics under a hard token budget: gold-in-pack
    rather than gold-in-top-K. Empty relevant → 0.0.
    """
    relevant = set(relevant_ids)
    if not relevant:
        return 0.0
    return 1.0 if relevant & set(included_ids) else 0.0


def pack_noise_rate(
    included_ids: Sequence[str],
    relevant_ids: Sequence[str] | set[str],
) -> float:
    """Fraction of pack-included ids that are not relevant (0 if pack empty)."""
    included = list(included_ids)
    if not included:
        return 0.0
    relevant = set(relevant_ids)
    noise = sum(1 for doc_id in included if doc_id not in relevant)
    return noise / len(included)


def mrr(
    ranked_ids: Sequence[str],
    relevant_ids: Sequence[str] | set[str],
) -> float:
    """Mean Reciprocal Rank of the first relevant hit (0 if none)."""
    relevant = set(relevant_ids)
    if not relevant:
        return 0.0
    for rank, doc_id in enumerate(ranked_ids, start=1):
        if doc_id in relevant:
            return 1.0 / rank
    return 0.0


def _dcg_at_k(gains: Sequence[float], k: int) -> float:
    total = 0.0
    for i, gain in enumerate(gains[:k]):
        # rank i+1; log2(i+2) for i starting at 0
        total += gain / math.log2(i + 2)
    return total


def ndcg_at_k(
    ranked_ids: Sequence[str],
    relevance_grades: Mapping[str, float],
    k: int,
) -> float:
    """Normalized DCG@k using graded relevance (missing ids grade as 0)."""
    if k <= 0:
        return 0.0
    gains = [float(relevance_grades.get(doc_id, 0.0)) for doc_id in list(ranked_ids)[:k]]
    dcg = _dcg_at_k(gains, k)
    ideal = sorted((float(g) for g in relevance_grades.values()), reverse=True)
    idcg = _dcg_at_k(ideal, k)
    if idcg <= 0.0:
        return 0.0
    return dcg / idcg


def binary_relevance_grades(
    relevant_ids: Sequence[str] | set[str],
    *,
    grade: float = 1.0,
) -> dict[str, float]:
    """Map relevant ids to a uniform positive grade for binary nDCG."""
    return {doc_id: grade for doc_id in relevant_ids}
