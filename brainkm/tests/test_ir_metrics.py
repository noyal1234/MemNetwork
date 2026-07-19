"""Unit tests for IR ranking metrics."""

from __future__ import annotations

from brainkm.services.ir_metrics import (
    binary_relevance_grades,
    mrr,
    ndcg_at_k,
    pack_noise_rate,
    recall_at_budget,
    recall_at_k,
)


def test_recall_at_k_perfect() -> None:
    ranked = ["a", "b", "c"]
    assert recall_at_k(ranked, ["a", "b"], k=2) == 1.0
    assert recall_at_k(ranked, ["a", "b"], k=1) == 0.5


def test_recall_at_k_empty_relevant() -> None:
    assert recall_at_k(["a"], [], k=5) == 0.0


def test_mrr_first_and_later() -> None:
    assert mrr(["rel", "x"], ["rel"]) == 1.0
    assert mrr(["x", "rel"], ["rel"]) == 0.5
    assert mrr(["x", "y"], ["rel"]) == 0.0


def test_ndcg_at_k_perfect_binary() -> None:
    grades = binary_relevance_grades(["a", "b"])
    assert ndcg_at_k(["a", "b", "c"], grades, k=2) == 1.0


def test_ndcg_at_k_imperfect() -> None:
    grades = {"a": 1.0, "b": 1.0}
    # Best possible at k=2 is [a,b]; we return [b, noise] then a later
    score = ndcg_at_k(["noise", "a", "b"], grades, k=2)
    assert 0.0 < score < 1.0


def test_ndcg_zero_when_no_grades() -> None:
    assert ndcg_at_k(["a"], {}, k=5) == 0.0


def test_recall_at_budget_any_hit() -> None:
    assert recall_at_budget(["a", "b", "c"], {"b", "z"}) == 1.0
    assert recall_at_budget(["a", "c"], {"b"}) == 0.0
    assert recall_at_budget([], {"b"}) == 0.0
    assert recall_at_budget(["a"], []) == 0.0


def test_pack_noise_rate() -> None:
    assert pack_noise_rate(["a", "b", "c"], {"a"}) == 2.0 / 3.0
    assert pack_noise_rate(["a", "b"], {"a", "b"}) == 0.0
    assert pack_noise_rate([], {"a"}) == 0.0
