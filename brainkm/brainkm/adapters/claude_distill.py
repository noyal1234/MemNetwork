"""Claude distill — MCP sampling when live, else ``claude -p``, else rules."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from brainkm.adapters.distill_prompts import SYSTEM_PROMPT, normalize_subtype, parse_json_array
from brainkm.adapters.distill_rules import RulesDistillAdapter
from brainkm.adapters.mcp_distill import _SAMPLING_CALLBACK, sampling_callback_usable
from brainkm.logging_config import get_logger
from brainkm.models.brain_config import BrainConfig
from brainkm.models.distill import DistilledNeuron, TranscriptRound

logger = get_logger("adapters.claude_distill")

CLAUDE_CLI_TIMEOUT_SECONDS = 90
CLAUDE_LLM_CONFIDENCE = 0.85


def resolve_claude_bin() -> str | None:
    path = shutil.which("claude")
    if path:
        return path
    local = Path.home() / ".local" / "bin" / "claude"
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    return None


class ClaudeDistillAdapter:
    """Foolproof Claude distill peer to CursorDistillAdapter."""

    mode = "claude"

    def __init__(
        self,
        config: BrainConfig,
        *,
        project_dir: Path | None = None,
    ) -> None:
        self._config = config
        self._project_dir = project_dir
        self._fallback = RulesDistillAdapter()
        self._claude_bin = resolve_claude_bin()

    def distill_rounds(
        self,
        rounds: tuple[TranscriptRound, ...],
        *,
        round_chunk_ids: dict[int, list[str]],
        max_total: int,
    ) -> list[DistilledNeuron]:
        if sampling_callback_usable():
            logger.info("Claude distill via MCP sampling")
            neurons = self._via_sampling(
                rounds, round_chunk_ids=round_chunk_ids, max_total=max_total
            )
            if neurons:
                return neurons

        if self._claude_bin:
            logger.info("Claude distill via %s -p", self._claude_bin)
            neurons = self._via_cli(rounds, round_chunk_ids=round_chunk_ids, max_total=max_total)
            if neurons:
                return neurons
            logger.warning("claude -p produced no neurons; falling back to rules")
        else:
            logger.info("claude CLI not found and sampling unavailable; using rules distill")

        return self._fallback.distill_rounds(
            rounds,
            round_chunk_ids=round_chunk_ids,
            max_total=max_total,
        )

    def _via_sampling(
        self,
        rounds: tuple[TranscriptRound, ...],
        *,
        round_chunk_ids: dict[int, list[str]],
        max_total: int,
    ) -> list[DistilledNeuron]:
        assert _SAMPLING_CALLBACK is not None
        neurons: list[DistilledNeuron] = []
        for round_ in rounds:
            if len(neurons) >= max_total:
                break
            chunk_ids = round_chunk_ids.get(round_.round_index, [])
            if not chunk_ids:
                continue
            raw = _SAMPLING_CALLBACK(
                system=SYSTEM_PROMPT,
                user=round_.combined_text[:8000],
                max_tokens=2000,
            )
            if not raw:
                continue
            neurons.extend(
                self._parse_items(raw, chunk_ids=chunk_ids, max_neurons=max_total - len(neurons))
            )
        return neurons[:max_total]

    def _via_cli(
        self,
        rounds: tuple[TranscriptRound, ...],
        *,
        round_chunk_ids: dict[int, list[str]],
        max_total: int,
    ) -> list[DistilledNeuron]:
        assert self._claude_bin is not None
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
                    [
                        self._claude_bin,
                        "-p",
                        prompt,
                        "--bare",
                        "--output-format",
                        "text",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=CLAUDE_CLI_TIMEOUT_SECONDS,
                    cwd=str(self._project_dir) if self._project_dir else None,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                logger.warning("claude -p distill failed: %s", exc)
                continue
            if completed.returncode != 0:
                logger.warning(
                    "claude -p exited %s: %s",
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
        return neurons[:max_total]

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
                    confidence=CLAUDE_LLM_CONFIDENCE,
                )
            )
            if len(neurons) >= max_neurons:
                break
        return neurons
