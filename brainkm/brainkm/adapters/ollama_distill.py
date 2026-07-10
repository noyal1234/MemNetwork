"""Local Ollama distill adapter."""

from __future__ import annotations

import json
import re
import sqlite3

from brainkm.adapters.distill_rules import RulesDistillAdapter
from brainkm.logging_config import get_logger
from brainkm.models.brain_config import BrainConfig
from brainkm.models.distill import DistilledNeuron, TranscriptRound
from brainkm.services.ollama_advisor import resolve_ollama_model

logger = get_logger("adapters.ollama_distill")

SYSTEM_PROMPT = """You are a memory-extraction assistant for a software project's local knowledge base.
Extract atomic project memory neurons from a chat round between a developer and a coding assistant.

Return ONLY a JSON array. Each item must have exactly these fields:
{"subtype":"decision|fact|rule|error","title":"...","body":"...","tags":["..."]}

Guidelines:
- One atomic fact per item — do not combine multiple ideas into one item.
- Do not produce summaries; each body must be independently verifiable.
- Keep body under 400 characters.
- Skip greetings, acknowledgements, and small talk — extract nothing if the round has no durable fact.
- Use "decision" for choices between alternatives, "rule" for conventions/constraints, \
"error" for bugs/pitfalls, "fact" for everything else.
- tags should be 2-6 lowercase concept keywords, not filler words.
- If nothing durable is present, return [].

Example input round:
USER: We decided to use JWT instead of session cookies for API auth.

ASSISTANT: Never store API keys in neurons. Access tokens expire after 15 minutes.

Example output:
[
  {"subtype":"decision","title":"Use JWT for API auth","body":"Chose JWT over session cookies for API authentication.","tags":["jwt","auth","api"]},
  {"subtype":"rule","title":"Never store API keys in neurons","body":"API keys must not be persisted in project memory.","tags":["security","secrets"]}
]
"""


def _build_context_block(conn: sqlite3.Connection | None, *, limit: int = 5) -> str:
    """Format recent non-ephemeral neurons to ground the model and avoid duplicates."""
    if conn is None:
        return ""

    from brainkm.services.memory import recent_neuron_context

    recent = recent_neuron_context(conn, limit=limit)
    if not recent:
        return ""

    lines = ["Recent project memory (avoid duplicating these; reuse existing tags where relevant):"]
    for item in recent:
        tag_str = ", ".join(item.tags) if item.tags else "none"
        lines.append(f"- [{item.subtype}] {item.title} (tags: {tag_str})")
    return "\n".join(lines) + "\n\n"


class OllamaDistillAdapter:
    mode = "ollama"

    def __init__(
        self,
        config: BrainConfig,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        self._config = config
        self._fallback = RulesDistillAdapter()
        self._model = resolve_ollama_model(config)
        self._context_block = _build_context_block(conn)

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

        user_message = f"{self._context_block}Round:\n{round_.combined_text[:8000]}"
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
            "format": "json",
        }
        url = f"{self._config.ollama.base_url.rstrip('/')}/api/chat"
        try:
            response = httpx.post(
                url,
                json=payload,
                timeout=self._config.ollama.timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            raw = body.get("message", {}).get("content", "")
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
