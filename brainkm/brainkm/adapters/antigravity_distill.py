"""Antigravity distill via ``agy -p`` / ``--print``, with rules fallback."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from brainkm.adapters.distill_prompts import SYSTEM_PROMPT, normalize_subtype, parse_json_array
from brainkm.adapters.distill_rules import RulesDistillAdapter
from brainkm.logging_config import get_logger
from brainkm.models.brain_config import BrainConfig
from brainkm.models.distill import DistilledNeuron, TranscriptRound

logger = get_logger("adapters.antigravity_distill")

AGY_CLI_TIMEOUT_SECONDS = 90
AGY_LLM_CONFIDENCE = 0.85


def resolve_agy_bin() -> str | None:
    path = shutil.which("agy")
    if path:
        return path
    local = Path.home() / ".local" / "bin" / "agy"
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    return None


class AntigravityDistillAdapter:
    """Peer to CursorDistillAdapter — shell out to Antigravity CLI print mode."""

    mode = "antigravity"

    def __init__(
        self,
        config: BrainConfig,
        *,
        project_dir: Path | None = None,
    ) -> None:
        self._config = config
        self._project_dir = project_dir
        self._fallback = RulesDistillAdapter()
        self._agy_bin = resolve_agy_bin()

    def distill_rounds(
        self,
        rounds: tuple[TranscriptRound, ...],
        *,
        round_chunk_ids: dict[int, list[str]],
        max_total: int,
    ) -> list[DistilledNeuron]:
        if not self._agy_bin:
            from brainkm.adapters.groq_distill import GroqDistillAdapter
            from brainkm.config import get_settings

            if get_settings().groq_api_key and self._config.capture.cloud_distill_acknowledged:
                logger.info("agy CLI not found; using Groq distill fallback")
                groq_adapter = GroqDistillAdapter(self._config)
                return groq_adapter.distill_rounds(
                    rounds,
                    round_chunk_ids=round_chunk_ids,
                    max_total=max_total,
                )
            logger.info("agy CLI not found; using rules distill")
            return self._fallback.distill_rounds(
                rounds,
                round_chunk_ids=round_chunk_ids,
                max_total=max_total,
            )

        logger.info("Antigravity distill via %s -p", self._agy_bin)
        neurons: list[DistilledNeuron] = []
        for round_ in rounds:
            if len(neurons) >= max_total:
                break
            chunk_ids = round_chunk_ids.get(round_.round_index, [])
            if not chunk_ids:
                continue
            prompt = (
                f"{SYSTEM_PROMPT}\n\nRound:\n{round_.combined_text[:8000]}\n\n"
                "Return ONLY a JSON array of memory neurons as specified."
            )
            try:
                completed = subprocess.run(
                    [self._agy_bin, "-p", prompt],
                    capture_output=True,
                    text=True,
                    timeout=AGY_CLI_TIMEOUT_SECONDS,
                    cwd=str(self._project_dir) if self._project_dir else None,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                logger.warning("agy -p distill failed: %s", exc)
                continue
            if completed.returncode != 0:
                logger.warning(
                    "agy -p exited %s: %s",
                    completed.returncode,
                    (completed.stderr or completed.stdout)[:300],
                )
                continue
            items = parse_json_array(completed.stdout or "")
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
                        confidence=AGY_LLM_CONFIDENCE,
                    )
                )
                if len(neurons) >= max_total:
                    break
        if neurons:
            return neurons[:max_total]
        logger.warning("agy -p produced no neurons; falling back to rules")
        return self._fallback.distill_rounds(
            rounds,
            round_chunk_ids=round_chunk_ids,
            max_total=max_total,
        )
