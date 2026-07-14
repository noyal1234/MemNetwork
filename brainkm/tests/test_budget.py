"""Tests for token budget truncation."""

from brainkm.models.brain_config import BrainConfig
from brainkm.services.budget import (
    BudgetLine,
    greedy_truncate,
    pre_tool_pack_slots,
    priority_for,
    truncate_by_channels,
)
from brainkm.services.memory import token_count


def _line(node_id: str, kind: str, subtype: str | None, title: str, *, approx_tokens: int, priority: int) -> BudgetLine:
    """Build a BudgetLine whose content actually costs ~approx_tokens."""
    content = ("lorem " * max(1, approx_tokens * 2)).strip()
    while token_count(f"{title}\n{content}") < approx_tokens:
        content += " ipsum dolor"
    while token_count(f"{title}\n{content}") > approx_tokens + 5 and len(content) > 20:
        content = content[: int(len(content) * 0.9)]
    tokens = token_count(f"{title}\n{content}")
    return BudgetLine(node_id, kind, subtype, title, content, tokens=tokens, priority=priority)


def test_priority_decision_beats_code() -> None:
    assert priority_for("memory", "decision") < priority_for("code", "file")


def test_greedy_truncate_respects_token_cap() -> None:
    lines = [
        _line("a", "memory", "decision", "A", approx_tokens=100, priority=0),
        _line("b", "memory", "fact", "B", approx_tokens=100, priority=3),
        _line("c", "code", "file", "C", approx_tokens=100, priority=7),
    ]
    included, manifest = greedy_truncate(lines, max_tokens=150)
    assert len(included) == 1
    assert included[0].node_id == "a"
    assert "b" in manifest.omitted_ids
    assert "c" in manifest.omitted_ids
    assert manifest.tokens_used <= 150


def test_truncate_by_channels_reserves_graph_slot() -> None:
    channels = {
        "neurons": [
            _line("n1", "memory", "decision", "N", approx_tokens=200, priority=0),
        ],
        "graph": [
            _line("g1", "code", "function", "G", approx_tokens=80, priority=9),
        ],
        "procedures": [],
    }
    slots = {"neurons": 150, "graph": 100, "procedures": 50}
    included, manifest = truncate_by_channels(channels, slots, dynamic_reallocation=False)
    ids = {line.node_id for line in included}
    assert "g1" in ids
    assert "n1" in ids
    n1 = next(line for line in included if line.node_id == "n1")
    assert n1.tokens <= 150
    assert manifest.tokens_used <= 250


def test_greedy_truncate_fits_oversized_first_line() -> None:
    line = _line("big", "memory", "decision", "Big", approx_tokens=2000, priority=0)
    included, manifest = greedy_truncate([line], max_tokens=100)
    assert len(included) == 1
    assert included[0].tokens <= 100
    assert manifest.tokens_used <= 100
    assert manifest.omitted_ids == []


def test_truncate_by_channels_reallocates_unused() -> None:
    channels = {
        "neurons": [
            _line("n1", "memory", "decision", "N1", approx_tokens=50, priority=0),
            _line("n2", "memory", "fact", "N2", approx_tokens=50, priority=3),
        ],
        "graph": [],
        "procedures": [],
    }
    slots = {"neurons": 60, "graph": 100, "procedures": 40}
    included, manifesto = truncate_by_channels(channels, slots, dynamic_reallocation=True)
    ids = {line.node_id for line in included}
    assert "n1" in ids
    assert "n2" in ids  # funded from unused graph/procedure budget
    assert manifesto.tokens_used >= 90


def test_pre_tool_pack_slots() -> None:
    slots = pre_tool_pack_slots(BrainConfig())
    assert slots["graph"] == 400
    assert slots["procedures"] == 250
    assert slots["neurons"] == 200
