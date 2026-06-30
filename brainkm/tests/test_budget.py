"""Tests for token budget truncation."""

from brainkm.services.budget import BudgetLine, greedy_truncate, priority_for


def test_priority_decision_beats_code() -> None:
    assert priority_for("memory", "decision") < priority_for("code", "file")


def test_greedy_truncate_respects_token_cap() -> None:
    lines = [
        BudgetLine("a", "memory", "decision", "A", "body", tokens=100, priority=0),
        BudgetLine("b", "memory", "fact", "B", "body", tokens=100, priority=3),
        BudgetLine("c", "code", "file", "C", "body", tokens=100, priority=7),
    ]
    included, manifest = greedy_truncate(lines, max_tokens=150)
    assert len(included) == 1
    assert included[0].node_id == "a"
    assert manifest.omitted_ids == ["b", "c"]
    assert manifest.tokens_used == 100
