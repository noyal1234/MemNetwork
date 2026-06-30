"""In-process recall rate limiting — max_recalls_per_turn with truncation exemption."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from brainkm.models.brain_config import BrainConfig


@dataclass
class RecallLimitState:
    window_seconds: float = 30.0
    turn_counts: dict[str, tuple[int, float]] = field(default_factory=dict)

    def check(
        self,
        session_id: str | None,
        config: BrainConfig,
        *,
        truncation_followup: bool = False,
    ) -> bool:
        """Return True when recall is allowed."""
        if truncation_followup:
            return True

        limit = config.injection.max_recalls_per_turn
        if limit <= 0:
            return True

        key = session_id or "__default__"
        now = time.monotonic()
        count, started = self.turn_counts.get(key, (0, now))

        if now - started > self.window_seconds:
            count = 0
            started = now

        if count >= limit:
            return False

        self.turn_counts[key] = (count + 1, started)
        return True


_recall_limit = RecallLimitState()


def get_recall_limit_state() -> RecallLimitState:
    return _recall_limit
