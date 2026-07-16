"""Distill timeout must return promptly without waiting for the orphaned worker."""

from __future__ import annotations

import time

from brainkm.adapters.distill import distill_rounds_with_timeout
from brainkm.models.brain_config import BrainConfig
from brainkm.models.distill import TranscriptMessage, TranscriptRound


class _SlowAdapter:
    mode = "slow"

    def distill_rounds(self, rounds, *, round_chunk_ids, max_total):  # noqa: ANN001
        _ = (rounds, round_chunk_ids, max_total)
        time.sleep(5)
        return []


def test_distill_timeout_returns_under_bound() -> None:
    rounds = (
        TranscriptRound(
            round_index=0,
            messages=(
                TranscriptMessage(role="user", text="We chose JWT for APIs.", line_no=1),
            ),
        ),
    )
    started = time.monotonic()
    neurons, mode = distill_rounds_with_timeout(
        _SlowAdapter(),
        rounds,
        round_chunk_ids={0: ["c1"]},
        max_total=5,
        timeout_seconds=1,
        config=BrainConfig(),
    )
    elapsed = time.monotonic() - started
    assert mode == "rules"
    assert isinstance(neurons, list)
    # Must not block for the full 5s sleep of the orphaned worker.
    assert elapsed < 3.0
