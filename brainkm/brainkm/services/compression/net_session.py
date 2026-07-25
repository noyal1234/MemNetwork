"""Net-session token accounting for optional terse-agent skill."""

from __future__ import annotations

from dataclasses import dataclass

from brainkm.services.memory import token_count

# Caveman-class skill tax estimate (input tokens / turn when skill is loaded).
DEFAULT_SKILL_TAX_TOKENS = 1200
SHORT_SESSION_TURN_THRESHOLD = 3


@dataclass(frozen=True)
class NetSessionTokens:
    skill_tax_input: int
    injected_in: int
    assistant_out: int
    total: int
    turns: int

    @property
    def likely_net_negative(self) -> bool:
        """Heuristic auto-disable for short / already-terse sessions."""
        return self.turns < SHORT_SESSION_TURN_THRESHOLD


def estimate_net_session(
    *,
    assistant_messages: list[str],
    injected_packs: list[str],
    skill_tax_per_turn: int = DEFAULT_SKILL_TAX_TOKENS,
    skill_enabled: bool = True,
) -> NetSessionTokens:
    turns = max(len(assistant_messages), 1)
    tax = (skill_tax_per_turn * turns) if skill_enabled else 0
    injected = sum(token_count(p) for p in injected_packs)
    out = sum(token_count(m) for m in assistant_messages)
    return NetSessionTokens(
        skill_tax_input=tax,
        injected_in=injected,
        assistant_out=out,
        total=tax + injected + out,
        turns=turns,
    )


def should_auto_disable_terse(
    *,
    turns: int,
    baseline_net: int,
    terse_net: int,
) -> bool:
    if turns < SHORT_SESSION_TURN_THRESHOLD:
        return True
    return terse_net >= baseline_net
