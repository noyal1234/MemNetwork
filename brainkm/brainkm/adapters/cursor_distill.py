"""Cursor distill adapter — agent CLI when available, else Cursor-aware heuristics."""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

from brainkm.adapters.cursor_clean import clean_cursor_text, distillable_round, is_distill_noise
from brainkm.adapters.distill_prompts import SYSTEM_PROMPT, build_context_block, normalize_subtype, parse_json_array
from brainkm.adapters.distill_rules import (
    DECISION_PATTERNS,
    ERROR_PATTERNS,
    RULE_PATTERNS,
    SENTENCE_SPLIT,
    _tags_from_text,
)
from brainkm.logging_config import get_logger
from brainkm.models.brain_config import BrainConfig
from brainkm.models.distill import DistilledNeuron, TranscriptRound
from brainkm.services.quality import INTERROGATIVE_LEAD

logger = get_logger("adapters.cursor_distill")

CURSOR_AGENT_TIMEOUT_SECONDS = 90
CURSOR_LLM_CONFIDENCE = 0.85
CURSOR_HEURISTIC_CONFIDENCE = 0.72


def pending_cursor_distill_path(project_dir: Path, session_id: str) -> Path:
    return project_dir / ".brain" / "pending" / "cursor-distill" / f"{session_id}.json"


def resolve_cursor_agent_bin() -> str | None:
    for name in ("agent", "cursor-agent"):
        path = shutil.which(name)
        if path:
            return path
    # Official installer places symlinks here even when not yet on shell PATH.
    local = Path.home() / ".local" / "bin"
    for name in ("agent", "cursor-agent"):
        candidate = local / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def load_predistilled_neurons(
    project_dir: Path | None,
    session_id: str | None,
    *,
    chunk_ids: list[str] | None = None,
) -> list[DistilledNeuron] | None:
    """Load neurons written by a Cursor-side distill pass, if present."""
    if project_dir is None or not session_id:
        return None
    path = pending_cursor_distill_path(project_dir, session_id)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Invalid pre-distilled file %s: %s", path, exc)
        return None

    items = raw.get("neurons") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return None

    neurons: list[DistilledNeuron] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        subtype = normalize_subtype(item.get("subtype"))
        if not subtype:
            continue
        neuron = DistilledNeuron(
            subtype=subtype,
            title=str(item.get("title", "")).strip(),
            body=str(item.get("body", "")).strip(),
            tags=[str(tag) for tag in item.get("tags", []) if tag],
            chunk_ids=list(chunk_ids or item.get("chunk_ids") or []),
            confidence=float(item.get("confidence", CURSOR_LLM_CONFIDENCE)),
        )
        if neuron.title and neuron.body and neuron.is_atomic() and not is_distill_noise(neuron.title):
            neurons.append(neuron)
    return neurons or None


def _classify_sentence(sentence: str) -> str:
    for pattern, subtype in DECISION_PATTERNS:
        if pattern.search(sentence):
            return subtype
    for pattern, subtype in RULE_PATTERNS:
        if pattern.search(sentence):
            return subtype
    for pattern, subtype in ERROR_PATTERNS:
        if pattern.search(sentence):
            return subtype
    return "fact"


def _title_from_sentence(sentence: str, *, max_len: int = 100) -> str:
    cleaned = re.sub(r"\s+", " ", sentence).strip()
    # Prefer ending at a clause boundary for titles.
    for sep in (": ", " — ", " - ", "; "):
        if sep in cleaned and len(cleaned.split(sep, 1)[0]) >= 12:
            cleaned = cleaned.split(sep, 1)[0].strip()
            break
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 3].rstrip() + "..."


def distill_cursor_round(
    round_: TranscriptRound,
    *,
    chunk_ids: list[str],
    max_neurons: int = 3,
) -> list[DistilledNeuron]:
    """Heuristic distill tuned for cleaned Cursor transcript rounds."""
    cleaned = distillable_round(round_)
    if cleaned is None:
        return []

    candidates: list[DistilledNeuron] = []
    for message in cleaned.messages:
        sentences = [part.strip() for part in SENTENCE_SPLIT.split(message.text) if part.strip()]
        for sentence in sentences:
            if is_distill_noise(sentence):
                continue
            if len(sentence) < 24:
                continue
            subtype = _classify_sentence(sentence)
            if subtype == "fact" and len(sentence) < 40:
                continue
            # User questions are not durable facts.
            if sentence.rstrip().endswith("?") or INTERROGATIVE_LEAD.match(sentence):
                continue

            body = sentence[:400].strip()
            title = _title_from_sentence(body)
            if is_distill_noise(title) or is_distill_noise(body):
                continue

            confidence = CURSOR_HEURISTIC_CONFIDENCE
            if subtype == "fact":
                confidence = 0.65

            neuron = DistilledNeuron(
                subtype=subtype,
                title=title,
                body=body,
                tags=_tags_from_text(body),
                chunk_ids=list(chunk_ids),
                confidence=confidence,
            )
            if neuron.is_atomic():
                candidates.append(neuron)

    priority = {"decision": 0, "rule": 1, "error": 2, "fact": 3}
    candidates.sort(key=lambda item: priority.get(item.subtype, 9))
    return candidates[:max_neurons]


class CursorDistillAdapter:
    """Distill via Cursor agent CLI when available; else Cursor-aware heuristics.

    Also consumes optional pre-distilled JSON at:
    `.brain/pending/cursor-distill/<session_id>.json`
    """

    mode = "cursor"

    def __init__(
        self,
        config: BrainConfig,
        *,
        conn: sqlite3.Connection | None = None,
        project_dir: Path | None = None,
        session_id: str | None = None,
        agent_bin: str | None = None,
    ) -> None:
        self._config = config
        self._conn = conn
        self._project_dir = project_dir
        self._session_id = session_id
        self._context_block = build_context_block(conn)
        self._agent_bin = agent_bin if agent_bin is not None else resolve_cursor_agent_bin()

    def distill_rounds(
        self,
        rounds: tuple[TranscriptRound, ...],
        *,
        round_chunk_ids: dict[int, list[str]],
        max_total: int,
    ) -> list[DistilledNeuron]:
        pre = load_predistilled_neurons(self._project_dir, self._session_id)
        if pre is not None:
            logger.info(
                "Using pre-distilled Cursor neurons for session %s (%d items)",
                self._session_id,
                len(pre),
            )
            # Attach first available chunk ids when pre-distill omitted them.
            if pre and not pre[0].chunk_ids:
                first_ids: list[str] = []
                for ids in round_chunk_ids.values():
                    if ids:
                        first_ids = list(ids)
                        break
                for neuron in pre:
                    neuron.chunk_ids = list(first_ids)
            return pre[:max_total]

        neurons: list[DistilledNeuron] = []
        use_agent = self._agent_bin is not None
        if use_agent:
            logger.info("Cursor agent distill via %s", self._agent_bin)
        else:
            logger.info("Cursor agent CLI not found; using Cursor-aware heuristic distill")

        for round_ in rounds:
            chunk_ids = round_chunk_ids.get(round_.round_index, [])
            if not chunk_ids:
                continue
            if use_agent:
                round_neurons = self._distill_round_via_agent(round_, chunk_ids=chunk_ids)
                if not round_neurons:
                    round_neurons = distill_cursor_round(round_, chunk_ids=chunk_ids)
            else:
                round_neurons = distill_cursor_round(round_, chunk_ids=chunk_ids)
            neurons.extend(round_neurons)
            if len(neurons) >= max_total:
                break
        return neurons[:max_total]

    def _distill_round_via_agent(
        self,
        round_: TranscriptRound,
        *,
        chunk_ids: list[str],
    ) -> list[DistilledNeuron]:
        assert self._agent_bin is not None
        cleaned = distillable_round(round_)
        if cleaned is None:
            return []

        round_text = "\n\n".join(
            f"{message.role.upper()}: {message.text}" for message in cleaned.messages
        )
        user_message = (
            f"{self._context_block}Round:\n{round_text[:8000]}\n\n"
            "Return ONLY a JSON array of memory neurons as specified."
        )
        prompt = f"{SYSTEM_PROMPT}\n\n{user_message}"

        try:
            completed = subprocess.run(
                [
                    self._agent_bin,
                    "-p",
                    prompt,
                    "--output-format",
                    "text",
                ],
                capture_output=True,
                text=True,
                timeout=CURSOR_AGENT_TIMEOUT_SECONDS,
                cwd=str(self._project_dir) if self._project_dir else None,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("Cursor agent distill failed: %s", exc)
            return []

        if completed.returncode != 0:
            logger.warning(
                "Cursor agent distill exited %s: %s",
                completed.returncode,
                (completed.stderr or completed.stdout)[:300],
            )
            return []

        parsed = parse_json_array(completed.stdout or "")
        neurons: list[DistilledNeuron] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            title = clean_cursor_text(str(item.get("title", "")))
            body = clean_cursor_text(str(item.get("body", "")))
            if not title or not body or is_distill_noise(title) or is_distill_noise(body):
                continue
            subtype = normalize_subtype(item.get("subtype"))
            if not subtype:
                continue
            neuron = DistilledNeuron(
                subtype=subtype,
                title=title,
                body=body,
                tags=[str(tag) for tag in item.get("tags", []) if tag],
                chunk_ids=list(chunk_ids),
                confidence=CURSOR_LLM_CONFIDENCE,
            )
            if neuron.is_atomic():
                neurons.append(neuron)
        return neurons
