"""MCP sampling distill — uses the client's model when sampling is available."""

from __future__ import annotations

from collections.abc import Callable

from brainkm.adapters.distill_prompts import SYSTEM_PROMPT, normalize_subtype, parse_json_array
from brainkm.adapters.distill_rules import RulesDistillAdapter
from brainkm.logging_config import get_logger
from brainkm.models.brain_config import BrainConfig
from brainkm.models.distill import DistilledNeuron, TranscriptRound

logger = get_logger("adapters.mcp_distill")

SamplingCallback = Callable[..., str | None]

# Set by the MCP server when a sampling-capable client session is active.
_SAMPLING_CALLBACK: SamplingCallback | None = None


def set_sampling_callback(callback: SamplingCallback) -> None:
    global _SAMPLING_CALLBACK
    _SAMPLING_CALLBACK = callback


def clear_sampling_callback() -> None:
    global _SAMPLING_CALLBACK
    _SAMPLING_CALLBACK = None


class McpDistillAdapter:
    """Ask the MCP host to distill via sampling; fall back to rules."""

    mode = "mcp"

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
        if _SAMPLING_CALLBACK is None:
            logger.info("MCP sampling unavailable — falling back to rules distill")
            return self._fallback.distill_rounds(
                rounds,
                round_chunk_ids=round_chunk_ids,
                max_total=max_total,
            )

        neurons: list[DistilledNeuron] = []
        try:
            for round_ in rounds:
                if len(neurons) >= max_total:
                    break
                chunk_ids = round_chunk_ids.get(round_.round_index, [])
                if not chunk_ids:
                    continue
                round_neurons = self._distill_round(
                    round_,
                    chunk_ids=chunk_ids,
                    max_neurons=max_total - len(neurons),
                )
                if round_neurons is None:
                    # Empty/failed sampling for this round → rules for that round only.
                    round_neurons = self._fallback.distill_rounds(
                        (round_,),
                        round_chunk_ids={round_.round_index: chunk_ids},
                        max_total=max_total - len(neurons),
                    )
                neurons.extend(round_neurons)
            if neurons:
                return neurons[:max_total]
        except Exception:  # noqa: BLE001
            logger.warning("MCP sampling distill failed; using rules", exc_info=True)
        return self._fallback.distill_rounds(
            rounds,
            round_chunk_ids=round_chunk_ids,
            max_total=max_total,
        )

    def _distill_round(
        self,
        round_: TranscriptRound,
        *,
        chunk_ids: list[str],
        max_neurons: int,
    ) -> list[DistilledNeuron] | None:
        """Return neurons, empty list if parse yielded nothing, or None to signal fallback."""
        assert _SAMPLING_CALLBACK is not None
        raw = _SAMPLING_CALLBACK(
            system=SYSTEM_PROMPT,
            user=round_.combined_text[:8000],
            max_tokens=2000,
        )
        if not raw:
            return None
        items = parse_json_array(raw)
        neurons: list[DistilledNeuron] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            subtype = normalize_subtype(item.get("subtype"))
            title = str(item.get("title") or "").strip()
            body = str(item.get("body") or "").strip()
            if not subtype or not title or not body:
                continue
            tags = item.get("tags") if isinstance(item.get("tags"), list) else []
            neurons.append(
                DistilledNeuron(
                    subtype=subtype,
                    title=title[:200],
                    body=body,
                    tags=[str(t).lower() for t in tags][:8],
                    chunk_ids=list(chunk_ids),
                    confidence=0.8,
                )
            )
            if len(neurons) >= max_neurons:
                break
        # Empty parse after non-empty raw → rules fallback for this round.
        return neurons if neurons else None
