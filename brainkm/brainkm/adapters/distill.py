"""Distill adapter protocol and mode router."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Protocol

from brainkm.logging_config import get_logger
from brainkm.models.brain_config import BrainConfig
from brainkm.models.distill import DistilledNeuron, TranscriptRound

logger = get_logger("adapters.distill")


class DistillAdapter(Protocol):
    mode: str

    def distill_rounds(
        self,
        rounds: tuple[TranscriptRound, ...],
        *,
        round_chunk_ids: dict[int, list[str]],
        max_total: int,
    ) -> list[DistilledNeuron]: ...


def get_distill_adapter(
    config: BrainConfig,
    *,
    conn: sqlite3.Connection | None = None,
) -> DistillAdapter:
    mode = config.capture.distill_mode
    if mode == "ollama":
        from brainkm.adapters.ollama_distill import OllamaDistillAdapter

        return OllamaDistillAdapter(config, conn=conn)
    if mode == "groq":
        from brainkm.adapters.groq_distill import GroqDistillAdapter

        return GroqDistillAdapter(config, conn=conn)
    if mode == "cursor":
        from brainkm.adapters.cursor_distill import CursorDistillAdapter

        return CursorDistillAdapter(config)
    if mode == "rules":
        from brainkm.adapters.distill_rules import RulesDistillAdapter

        return RulesDistillAdapter()


def distill_rounds_with_timeout(
    adapter: DistillAdapter,
    rounds: tuple[TranscriptRound, ...],
    *,
    round_chunk_ids: dict[int, list[str]],
    max_total: int,
    timeout_seconds: int | None,
    config: BrainConfig,
) -> tuple[list[DistilledNeuron], str]:
    """Run distill with optional timeout; fall back to rules on timeout."""
    if timeout_seconds is None or timeout_seconds <= 0:
        return adapter.distill_rounds(
            rounds,
            round_chunk_ids=round_chunk_ids,
            max_total=max_total,
        ), adapter.mode

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            adapter.distill_rounds,
            rounds,
            round_chunk_ids=round_chunk_ids,
            max_total=max_total,
        )
        try:
            return future.result(timeout=timeout_seconds), adapter.mode
        except FuturesTimeoutError:
            logger.warning(
                "distill timed out after %ss (mode=%s); falling back to rules",
                timeout_seconds,
                adapter.mode,
            )
            from brainkm.adapters.distill_rules import RulesDistillAdapter

            rules = RulesDistillAdapter()
            return rules.distill_rounds(
                rounds,
                round_chunk_ids=round_chunk_ids,
                max_total=max_total,
            ), "rules"