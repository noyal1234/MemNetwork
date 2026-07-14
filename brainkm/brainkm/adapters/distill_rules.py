"""Rule-based atomic distill — offline fallback."""

from __future__ import annotations

import re

from brainkm.adapters.cursor_clean import distillable_round, is_distill_noise
from brainkm.models.distill import DistilledNeuron, TranscriptRound

DECISION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:decided|decision|chose|choose|going with|we'll use)\b", re.I), "decision"),
    (re.compile(r"\b(?:instead of|rather than)\b", re.I), "decision"),
)

RULE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:always|never|must|required|convention)\b", re.I), "rule"),
    (re.compile(r"\b(?:do not|don't)\b", re.I), "rule"),
)

ERROR_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:pitfall|bug|race condition|failed)\b", re.I), "error"),
)

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _tags_from_text(text: str) -> list[str]:
    tokens = re.findall(r"\b[a-z][a-z0-9_-]{2,}\b", text.lower())
    stop = {"the", "and", "with", "that", "this", "from", "have", "will", "instead", "because"}
    seen: set[str] = set()
    tags: list[str] = []
    for token in tokens:
        if token in stop or token in seen:
            continue
        seen.add(token)
        tags.append(token)
        if len(tags) >= 6:
            break
    return tags


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


_ROLE_PREFIX = re.compile(r"^(?:USER|ASSISTANT|SYSTEM|TOOL)\s*:\s*", re.IGNORECASE)


def _strip_role_prefix(sentence: str) -> str:
    return _ROLE_PREFIX.sub("", sentence).strip()


def _title_from_sentence(sentence: str, *, max_words: int = 8, max_len: int = 80) -> str:
    cleaned = re.sub(r"\s+", " ", sentence).strip()
    # Prefer the clause before a dash/colon for tighter titles.
    for sep in (" — ", " - ", ": "):
        if sep in cleaned:
            cleaned = cleaned.split(sep, 1)[0].strip()
            break
    words = cleaned.split()
    if len(words) > max_words:
        cleaned = " ".join(words[:max_words])
    if len(cleaned) > max_len:
        return cleaned[: max_len - 3].rstrip() + "..."
    return cleaned.rstrip(".,;:")


def distill_round(
    round_: TranscriptRound,
    *,
    chunk_ids: list[str],
    max_neurons: int = 3,
) -> list[DistilledNeuron]:
    cleaned = distillable_round(round_)
    if cleaned is None:
        return []
    text = cleaned.combined_text
    sentences = [part.strip() for part in SENTENCE_SPLIT.split(text) if part.strip()]
    candidates: list[DistilledNeuron] = []

    for sentence in sentences:
        sentence = _strip_role_prefix(sentence)
        if len(sentence) < 20:
            continue
        if is_distill_noise(sentence):
            continue
        if sentence.lower().startswith("[tool_use:"):
            continue
        subtype = _classify_sentence(sentence)
        if subtype == "fact" and len(sentence) < 40:
            continue

        neuron = DistilledNeuron(
            subtype=subtype,
            title=_title_from_sentence(sentence),
            body=sentence[:400],
            tags=_tags_from_text(sentence),
            chunk_ids=list(chunk_ids),
            confidence=0.55,
        )
        if neuron.is_atomic():
            candidates.append(neuron)

    # Prefer higher-signal subtypes first.
    priority = {"decision": 0, "rule": 1, "error": 2, "fact": 3}
    candidates.sort(key=lambda item: priority.get(item.subtype, 9))
    return candidates[:max_neurons]


class RulesDistillAdapter:
    mode = "rules"

    def distill_rounds(
        self,
        rounds: tuple[TranscriptRound, ...],
        *,
        round_chunk_ids: dict[int, list[str]],
        max_total: int,
    ) -> list[DistilledNeuron]:
        return distill_rounds(
            rounds,
            round_chunk_ids=round_chunk_ids,
            max_total=max_total,
        )


def distill_rounds(
    rounds: tuple[TranscriptRound, ...],
    *,
    round_chunk_ids: dict[int, list[str]],
    max_neurons_per_round: int = 2,
    max_total: int = 50,
) -> list[DistilledNeuron]:
    neurons: list[DistilledNeuron] = []
    for round_ in rounds:
        chunk_ids = round_chunk_ids.get(round_.round_index, [])
        if not chunk_ids:
            continue
        neurons.extend(
            distill_round(round_, chunk_ids=chunk_ids, max_neurons=max_neurons_per_round)
        )
        if len(neurons) >= max_total:
            break
    return neurons[:max_total]
