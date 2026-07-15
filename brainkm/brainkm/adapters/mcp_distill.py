"""MCP sampling distill — uses the client's model when sampling is available."""

from __future__ import annotations

from brainkm.adapters.distill_prompts import SYSTEM_PROMPT, normalize_subtype, parse_json_array
from brainkm.adapters.distill_rules import RulesDistillAdapter
from brainkm.logging_config import get_logger
from brainkm.models.brain_config import BrainConfig
from brainkm.models.distill import DistilledNeuron, TranscriptRound

logger = get_logger("adapters.mcp_distill")

# Set by the MCP server when a sampling-capable client session is active.
_SAMPLING_CALLBACK = None


def set_sampling_callback(callback) -> None:  # noqa: ANN001
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
        try:
            transcript = "\n\n".join(r.combined_text for r in rounds)
            raw = _SAMPLING_CALLBACK(
                system=SYSTEM_PROMPT,
                user=transcript[:12000],
                max_tokens=2000,
            )
            if not raw:
                raise RuntimeError("empty sampling response")
            items = parse_json_array(raw)
            neurons: list[DistilledNeuron] = []
            # Attach chunk ids from first round as rough provenance.
            default_chunks = next(iter(round_chunk_ids.values()), [])
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
                        chunk_ids=list(default_chunks),
                        confidence=0.8,
                    )
                )
                if len(neurons) >= max_total:
                    break
            if neurons:
                return neurons
        except Exception:  # noqa: BLE001
            logger.warning("MCP sampling distill failed; using rules", exc_info=True)
        return self._fallback.distill_rounds(
            rounds,
            round_chunk_ids=round_chunk_ids,
            max_total=max_total,
        )
