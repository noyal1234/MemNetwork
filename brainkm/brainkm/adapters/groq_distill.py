"""Cloud Groq distill adapter (OpenAI-compatible chat completions)."""

from __future__ import annotations

import sqlite3

from brainkm.adapters.cursor_clean import distillable_round, is_distill_noise
from brainkm.adapters.distill_prompts import (
    SYSTEM_PROMPT,
    build_context_block,
    normalize_subtype,
    parse_json_array,
)
from brainkm.adapters.distill_rules import RulesDistillAdapter
from brainkm.config import get_settings
from brainkm.logging_config import get_logger
from brainkm.models.brain_config import BrainConfig
from brainkm.models.distill import DistilledNeuron, TranscriptRound

logger = get_logger("adapters.groq_distill")


class GroqDistillAdapter:
    mode = "groq"

    def __init__(
        self,
        config: BrainConfig,
        *,
        conn: sqlite3.Connection | None = None,
        api_key: str | None = None,
    ) -> None:
        self._config = config
        self._fallback = RulesDistillAdapter()
        self._model = config.groq.model
        self._context_block = build_context_block(conn)
        self._api_key = api_key if api_key is not None else get_settings().groq_api_key

    def distill_rounds(
        self,
        rounds: tuple[TranscriptRound, ...],
        *,
        round_chunk_ids: dict[int, list[str]],
        max_total: int,
    ) -> list[DistilledNeuron]:
        if not self._api_key:
            logger.warning("GROQ_API_KEY not set; falling back to rules distill")
            return self._fallback.distill_rounds(
                rounds,
                round_chunk_ids=round_chunk_ids,
                max_total=max_total,
            )

        if not self._groq_available():
            logger.warning("Groq unreachable; falling back to rules distill")
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

    def _groq_available(self) -> bool:
        try:
            import httpx
        except ImportError:
            logger.warning("httpx not installed; install brainkm[cloud]")
            return False

        url = f"{self._config.groq.base_url.rstrip('/')}/models"
        try:
            response = httpx.get(
                url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=2.0,
            )
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

        cleaned = distillable_round(round_)
        if cleaned is None:
            return []
        user_message = f"{self._context_block}Round:\n{cleaned.combined_text[:8000]}"
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        url = f"{self._config.groq.base_url.rstrip('/')}/chat/completions"
        try:
            response = httpx.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self._config.groq.timeout_seconds,
            )
            if response.status_code == 429:
                logger.warning("Groq rate limited (429); falling back to rules distill")
                from brainkm.adapters import distill_rules

                return distill_rules.distill_round(round_, chunk_ids=chunk_ids)
            response.raise_for_status()
            body = response.json()
            choices = body.get("choices") or []
            raw = ""
            if choices:
                raw = choices[0].get("message", {}).get("content", "") or ""
        except Exception as exc:
            logger.warning("Groq distill failed: %s", exc)
            from brainkm.adapters import distill_rules

            return distill_rules.distill_round(round_, chunk_ids=chunk_ids)

        parsed = parse_json_array(raw)
        neurons: list[DistilledNeuron] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            subtype = normalize_subtype(item.get("subtype", "fact"))
            if subtype is None:
                continue
            title = str(item.get("title", "")).strip()
            body_text = str(item.get("body", "")).strip()
            if is_distill_noise(title) or is_distill_noise(body_text):
                continue
            neuron = DistilledNeuron(
                subtype=subtype,
                title=title,
                body=body_text,
                tags=[str(tag) for tag in item.get("tags", []) if tag],
                chunk_ids=list(chunk_ids),
                confidence=0.8,
            )
            if neuron.title and neuron.body and neuron.is_atomic():
                neurons.append(neuron)
        return neurons
