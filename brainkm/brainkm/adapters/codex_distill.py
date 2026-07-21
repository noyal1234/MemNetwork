"""Codex distill via ``codex exec``, with rules fallback."""

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

logger = get_logger("adapters.codex_distill")

CODEX_CLI_TIMEOUT_SECONDS = 120
CODEX_LLM_CONFIDENCE = 0.85


def resolve_codex_bin() -> str | None:
    path = shutil.which("codex")
    if path:
        return path
    local = Path.home() / ".local" / "bin" / "codex"
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    return None


class CodexDistillAdapter:
    """Peer to ClaudeDistillAdapter — shell out to ``codex exec`` (non-interactive)."""

    mode = "codex"

    def __init__(
        self,
        config: BrainConfig,
        *,
        project_dir: Path | None = None,
    ) -> None:
        self._config = config
        self._project_dir = project_dir
        self._fallback = RulesDistillAdapter()
        self._codex_bin = resolve_codex_bin()

    def distill_rounds(
        self,
        rounds: tuple[TranscriptRound, ...],
        *,
        round_chunk_ids: dict[int, list[str]],
        max_total: int,
    ) -> list[DistilledNeuron]:
        if not self._codex_bin:
            logger.info("codex CLI not found; using rules distill")
            return self._fallback.distill_rounds(
                rounds,
                round_chunk_ids=round_chunk_ids,
                max_total=max_total,
            )

        logger.info("Codex distill via %s exec", self._codex_bin)
        neurons: list[DistilledNeuron] = []
        for round_ in rounds:
            if len(neurons) >= max_total:
                break
            chunk_ids = round_chunk_ids.get(round_.round_index, [])
            if not chunk_ids:
                continue
            prompt = (
                f"{SYSTEM_PROMPT}\n\nRound:\n{round_.combined_text[:8000]}\n\n"
                "Return ONLY a JSON array of memory neurons as specified. "
                "Do not edit files or run tools — answer with the JSON array only."
            )
            try:
                # read-only + never ask: distill must stay unattended and non-mutating.
                completed = subprocess.run(
                    [
                        self._codex_bin,
                        "exec",
                        "--sandbox",
                        "read-only",
                        "--ask-for-approval",
                        "never",
                        "--ephemeral",
                        prompt,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=CODEX_CLI_TIMEOUT_SECONDS,
                    cwd=str(self._project_dir) if self._project_dir else None,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                logger.warning("codex exec distill failed: %s", exc)
                continue
            if completed.returncode != 0:
                logger.warning(
                    "codex exec exited %s: %s",
                    completed.returncode,
                    (completed.stderr or completed.stdout)[:300],
                )
                continue
            neurons.extend(
                self._parse_items(
                    completed.stdout or "",
                    chunk_ids=chunk_ids,
                    max_neurons=max_total - len(neurons),
                )
            )
        if neurons:
            return neurons[:max_total]
        logger.warning("codex exec produced no neurons; falling back to rules")
        return self._fallback.distill_rounds(
            rounds,
            round_chunk_ids=round_chunk_ids,
            max_total=max_total,
        )

    def _parse_items(
        self,
        raw: str,
        *,
        chunk_ids: list[str],
        max_neurons: int,
    ) -> list[DistilledNeuron]:
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
                    confidence=CODEX_LLM_CONFIDENCE,
                )
            )
            if len(neurons) >= max_neurons:
                break
        return neurons
