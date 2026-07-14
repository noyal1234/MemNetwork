"""Lightweight quality guards for auto-captured neurons."""

from __future__ import annotations

import re

from brainkm.models.distill import DistilledNeuron

MIN_TITLE_LEN = 4
MIN_BODY_LEN = 12
MAX_TITLE_LEN = 200
BOILERPLATE = re.compile(
    r"^(thanks|thank you|ok|okay|sure|done|yes|no|hello|hi)\.?$",
    re.IGNORECASE,
)
TRANSCRIPT_CHROME = re.compile(
    r"(?is)(?:^|\n)\s*(?:user|assistant|system)\s*:|"
    r"<user_query>|"
    r"</user_query>|"
    r"<timestamp>|"
    r"\[tool_use:",
)


def passes_quality_gate(item: DistilledNeuron) -> bool:
    title = item.title.strip()
    body = (item.body or "").strip()
    if len(title) < MIN_TITLE_LEN or len(title) > MAX_TITLE_LEN:
        return False
    if len(body) < MIN_BODY_LEN:
        return False
    if BOILERPLATE.match(title):
        return False
    if TRANSCRIPT_CHROME.search(title) or TRANSCRIPT_CHROME.search(body):
        return False
    if not item.is_atomic():
        return False
    return True


def filter_distilled(
    items: list[DistilledNeuron],
    *,
    max_count: int,
) -> list[DistilledNeuron]:
    accepted: list[DistilledNeuron] = []
    for item in items:
        if len(accepted) >= max_count:
            break
        if passes_quality_gate(item):
            accepted.append(item)
    return accepted
