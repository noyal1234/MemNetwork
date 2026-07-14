"""Tests for token budget truncation."""

from brainkm.models.brain_config import BrainConfig
from brainkm.services.budget import (
    BudgetLine,
    greedy_truncate,
    pre_tool_pack_slots,
    priority_for,
    truncate_by_channels,
)


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


def test_truncate_by_channels_reserves_graph_slot() -> None:
    channels = {
        "neurons": [
            BudgetLine("n1", "memory", "decision", "N", "body", tokens=200, priority=0),
        ],
        "graph": [
            BudgetLine("g1", "code", "function", "G", "body", tokens=80, priority=9),
        ],
        "procedures": [],
    }
    slots = {"neurons": 150, "graph": 100, "procedures": 50}
    included, manifest = truncate_by_channels(channels, slots, dynamic_reallocation=False)
    ids = {line.node_id for line in included}
    assert "g1" in ids
    assert "n1" in ids  # first neuron may still fit via greedy first-item rule
    assert manifest.tokens_used >= 80


def test_truncate_by_channels_reallocates_unused() -> None:
    channels = {
        "neurons": [
            BudgetLine("n1", "memory", "decision", "N1", "body", tokens=50, priority=0),
            BudgetLine("n2", "memory", "fact", "N2", "body", tokens=50, priority=3),
        ],
        "graph": [],
        "procedures": [],
    }
    slots = {"neurons": 60, "graph": 100, "procedures": 40}
    included, manifest = truncate_by_channels(channels, slots, dynamic_reallocation=True)
    ids = {line.node_id for line in included}
    assert "n1" in ids
    assert "n2" in ids  # funded from unused graph/procedure budget
    assert manifest.tokens_used == 100


def test_pre_tool_pack_slots() -> None:
    slots = pre_tool_pack_slots(BrainConfig())
    assert slots["graph"] == 400
    assert slots["procedures"] == 250
    assert slots["neurons"] == 200
