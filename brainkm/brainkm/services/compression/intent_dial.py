"""Intent × subtype intensity dial for pack egress."""

from __future__ import annotations

from brainkm.services.compression.types import ProseIntensity
from brainkm.services.intent import QueryIntent, classify_intent


def prose_intensity_for_query(
    query: str,
    *,
    subtype: str | None,
    default: ProseIntensity = "lite",
) -> ProseIntensity:
    """WHY/IMPACT keep denser decisions; GENERAL more aggressive on prose."""
    if subtype in {"decision", "rule"}:
        # Default store/egress safety: off unless caller opts into lossy+rubric
        return "off"
    intent = classify_intent(query)
    if intent in {QueryIntent.WHY, QueryIntent.IMPACT, QueryIntent.TEMPORAL}:
        return "lite" if default != "off" else "off"
    if intent == QueryIntent.DEBUG:
        return "lite"
    if intent == QueryIntent.GENERAL:
        return "full" if default == "full" else "lite"
    return default
