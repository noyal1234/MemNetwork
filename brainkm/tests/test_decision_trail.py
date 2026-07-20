"""Unit tests for decision trail history gating and trimming."""

from __future__ import annotations

from brainkm.models.schemas import DecisionTrailEntry
from brainkm.services.decision_trail import (
    should_include_history,
    trim_decision_trail,
)


def test_should_include_history_uses_real_intents() -> None:
    assert should_include_history(include_history=None, intent="why", query="x") is True
    assert (
        should_include_history(include_history=None, intent="temporal", query="x") is True
    )
    assert (
        should_include_history(include_history=None, intent="impact", query="calls foo")
        is False
    )
    # Dead labels from an earlier draft must not auto-enable.
    assert (
        should_include_history(include_history=None, intent="decision", query="x")
        is False
    )
    assert should_include_history(include_history=None, intent="rule", query="x") is False


def test_should_include_history_respects_explicit_flag() -> None:
    assert (
        should_include_history(include_history=False, intent="why", query="why jwt")
        is False
    )
    assert (
        should_include_history(include_history=True, intent="general", query="x") is True
    )


def test_should_include_history_keyword_fallback() -> None:
    assert (
        should_include_history(
            include_history=None, intent="general", query="previously we used sessions"
        )
        is True
    )


def test_trim_decision_trail_respects_budget() -> None:
    entries = [
        DecisionTrailEntry(node_id=f"n{i}", title=f"Decision title number {i} " * 5)
        for i in range(8)
    ]
    # Each entry is ~26 tokens; budget=40 keeps the newest only.
    trimmed = trim_decision_trail(entries, budget=40)
    assert len(trimmed) == 1
    assert trimmed[0].node_id == "n0"
    assert trim_decision_trail(entries, budget=0) == []
