"""Local Ollama distill adapter."""

from __future__ import annotations

import json
import re

from brainkm.adapters.distill_rules import RulesDistillAdapter
from brainkm.logging_config import get_logger
from brainkm.models.brain_config import BrainConfig
from brainkm.models.distill import DistilledNeuron, TranscriptRound

logger = get_logger("adapters.ollama_distill")

DISTILL_PROMPT = """Extract atomic project memory neurons from this dev chat round.
Return ONLY a JSON array. Each item:
{"subtype":"decision|fact|rule|error","title":"...","body":"...","tags":["..."]}.
Rules: one fact per item; no summaries; body under 400 chars; skip small talk.

Round:
{round_text}
"""


class OllamaDistillAdapter:
    mode = "ollama"

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
        if not self._ollama_available():
            logger.warning("Ollama unreachable; falling back to rules distill")
            return self._fallback.distill_rounds(
                rounds,
                round_chunk_ids=round_chunk_ids,
                max_total=max_total,
            )

        neurons: list[DistilledNeuron] = []
        for round_ in rounds:
            chunk_ids = round_chunk_ids.get(round_.round_index, [])
            if not chunk_ids:
                continue
            round_neurons = self._distill_round(round_, chunk_ids=chunk_ids)
            neurons.extend(round_neurons)
            if len(neurons) >= max_total:
                break
        return neurons[:max_total]

    def _ollama_available(self) -> bool:
        try:
            import httpx
        except ImportError:
            logger.warning("httpx not installed; install brainkm[ollama]")
            return False

        url = f"{self._config.ollama.base_url.rstrip('/')}/api/tags"
        try:
            response = httpx.get(url, timeout=2.0)
            return response.status_code == 200
        except Exception:
            return False

    def _distill_round(
        self,
        round_: TranscriptRound,
        *,
        chunk_ids: list[str],
    ) -> list[DistilledNeuron]:
        import httpx

        prompt = DISTILL_PROMPT.format(round_text=round_.combined_text[:8000])
        payload = {
            "model": self._config.ollama.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }
        url = f"{self._config.ollama.base_url.rstrip('/')}/api/generate"
        try:
            response = httpx.post(
                url,
                json=payload,
                timeout=self._config.ollama.timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            raw = body.get("response", "")
        except Exception as exc:
            logger.warning("Ollama distill failed: %s", exc)
            from brainkm.adapters import distill_rules

            return distill_rules.distill_round(round_, chunk_ids=chunk_ids)

        parsed = _parse_json_array(raw)
        neurons: list[DistilledNeuron] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            neuron = DistilledNeuron(
                subtype=str(item.get("subtype", "fact")),
                title=str(item.get("title", "")).strip(),
                body=str(item.get("body", "")).strip(),
                tags=[str(tag) for tag in item.get("tags", []) if tag],
                chunk_ids=list(chunk_ids),
                confidence=0.75,
            )
            if neuron.title and neuron.body and neuron.is_atomic():
                neurons.append(neuron)
        return neurons


def _parse_json_array(raw: str) -> list[object]:
    raw = raw.strip()
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("neurons"), list):
            return data["neurons"]
    except json.JSONDecodeError:
        pass

    match = re.search(r"\[[\s\S]*\]", raw)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []
