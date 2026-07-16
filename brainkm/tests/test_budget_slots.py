"""Budget slot allocation stays non-negative and within total."""

from __future__ import annotations

from brainkm.models.brain_config import BrainConfig, BudgetConfig, PreToolBudget
from brainkm.services.budget import adaptive_token_budget, context_pack_slots


def _cfg(total: int, *, dynamic: bool = True) -> BrainConfig:
    return BrainConfig(
        budget=BudgetConfig(
            total_tokens=total,
            dynamic_reallocation=dynamic,
            pre_tool=PreToolBudget(graph_neighborhood=400, procedure_expanded=200),
        )
    )


def test_slots_never_negative_at_low_budget() -> None:
    cfg = _cfg(200)
    for query in (
        "edit src/foo.py AuthService",
        "why did we choose JWT",
        "debug null pointer in recall",
        "project overview",
    ):
        slots = context_pack_slots(cfg, query)
        assert all(v >= 0 for v in slots.values()), (query, slots)
        assert sum(slots.values()) <= adaptive_token_budget(cfg, query)


def test_slots_sum_within_total_at_default() -> None:
    cfg = _cfg(1500)
    slots = context_pack_slots(cfg, "what calls AuthService")
    assert sum(slots.values()) <= 1500
    assert slots["neurons"] >= 0
    assert slots["graph"] >= 0
    assert slots["procedures"] >= 0


def test_static_slots_within_total() -> None:
    cfg = _cfg(200, dynamic=False)
    slots = context_pack_slots(cfg, None)
    assert sum(slots.values()) <= 200
    assert all(v >= 0 for v in slots.values())
