"""Cursor-model distill adapter (V1: rules fallback outside hook context)."""

from __future__ import annotations

from brainkm.adapters.distill_rules import RulesDistillAdapter
from brainkm.logging_config import get_logger
from brainkm.models.brain_config import BrainConfig
from brainkm.models.distill import DistilledNeuron, TranscriptRound

logger = get_logger("adapters.cursor_distill")


class CursorDistillAdapter:
    """Distill via Cursor's model when invoked from SessionEnd/PreCompact hooks.

    Standalone `brainkm capture` has no Cursor LLM bridge in V1 — falls back to
    rules with a warning. Hook integration can pass pre-distilled JSON later.
    """

    mode = "cursor"

    def __init__(self, config: BrainConfig) -> None:
        self._config = config
        self._fallback = RulesDistillAdapter()

    def distill_rounds(
        self,
        rounds: tuple[TranscriptRound, ...],
        *,
        round_chunk_ids: dict[int, list[str]],
        max_total: int,
    ) -> list[DistilledNeuron]:
        logger.warning(
            "cursor distill_mode has no standalone LLM bridge in V1; using rules fallback"
        )
        return self._fallback.distill_rounds(
            rounds,
            round_chunk_ids=round_chunk_ids,
            max_total=max_total,
        )
