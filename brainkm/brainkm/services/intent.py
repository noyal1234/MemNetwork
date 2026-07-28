"""Query intent routing for channel mix and budget targeting."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class QueryIntent(StrEnum):
    LOCATE = "locate"
    WHY = "why"
    IMPACT = "impact"
    TEMPORAL = "temporal"
    DEBUG = "debug"
    GENERAL = "general"


@dataclass(frozen=True)
class IntentRouting:
    intent: QueryIntent
    boost_subtypes: tuple[str, ...]
    graph_hops: int
    prefer_vector: bool
    prefer_graph: bool
    time_filter: bool
    token_budget_fraction: float


_PATH_HINT = re.compile(r"[\w./-]+\.(py|ts|tsx|js|jsx|go|rs|java|md)\b")
_WHY = re.compile(
    r"\b(why|reason|rationale|decision|chose|chosen|instead of|pivot|trade-?off)\b",
    re.I,
)
_IMPACT = re.compile(
    r"\b(what calls|who calls|impact|blast.?radius|depend|imports?|breaks if)\b",
    re.I,
)
_TEMPORAL = re.compile(
    r"\b(when|before|after|previously|used to|superseded|history|timeline)\b",
    re.I,
)
_DEBUG = re.compile(
    r"\b(error|bug|fix|fail(s|ed|ing|ure)?|broken|exception|stack|crash|"
    r"traceback|regression|misconfigur\w*|[A-Za-z]*Error|[A-Za-z]*Exception)\b",
    re.I,
)
# Symptom-side phrasing: what a user types before they know the cause. These
# queries are cause-seeking, but carry none of the _DEBUG error vocabulary.
_SYMPTOM = re.compile(
    r"("
    r"\b(not|never|no longer|stopped|isn'?t|aren'?t|doesn'?t|don'?t|won'?t|wasn'?t)\b"
    r"[\w\s]{0,20}?"
    r"\b(work\w*|call\w*|fir\w*|run\w*|load\w*|start\w*|trigger\w*|inject\w*|appear\w*|show\w*|us\w*)\b"
    r"|\b(silent\w*|silently|hangs?|hung|stuck|nothing happens|no output|"
    r"empty|missing|ignored|skipped|quiet)\b"
    r")",
    re.I,
)
# Decision-seeking markers keep genuine "why did we choose X" in WHY even when
# the same sentence mentions a failure.
_DECISION_MARKER = re.compile(
    r"\b(chose|chosen|choose|instead of|trade-?off|decision|pivot|rationale)\b",
    re.I,
)
_LOCATE = re.compile(
    r"\b(where is|find|locate|defined|definition|symbol)\b",
    re.I,
)
# Personal / off-domain prompts that share keywords with project neurons (theme leak).
_OFF_DOMAIN = re.compile(
    r"\b("
    r"wifi|password|passphrase|cabin|neighbor|nba\s+finals|weather|rain\s+in|"
    r"grocery|recipe|birthday|dog'?s?\s+name|name\s+for\s+my\s+dog|"
    r"cafe\s+wifi|lodge\s+wifi"
    r")\b",
    re.I,
)

_ROUTING: dict[QueryIntent, IntentRouting] = {
    QueryIntent.LOCATE: IntentRouting(
        intent=QueryIntent.LOCATE,
        boost_subtypes=(),
        graph_hops=1,
        prefer_vector=False,
        prefer_graph=True,
        time_filter=False,
        token_budget_fraction=0.7,
    ),
    QueryIntent.WHY: IntentRouting(
        intent=QueryIntent.WHY,
        boost_subtypes=("decision", "rule", "fact"),
        graph_hops=2,
        prefer_vector=True,
        prefer_graph=False,
        time_filter=True,
        token_budget_fraction=0.55,
    ),
    QueryIntent.IMPACT: IntentRouting(
        intent=QueryIntent.IMPACT,
        boost_subtypes=(),
        graph_hops=2,
        prefer_vector=False,
        prefer_graph=True,
        time_filter=False,
        token_budget_fraction=0.85,
    ),
    QueryIntent.TEMPORAL: IntentRouting(
        intent=QueryIntent.TEMPORAL,
        boost_subtypes=("decision", "fact", "error"),
        graph_hops=2,
        prefer_vector=True,
        prefer_graph=False,
        time_filter=True,
        token_budget_fraction=0.6,
    ),
    QueryIntent.DEBUG: IntentRouting(
        intent=QueryIntent.DEBUG,
        boost_subtypes=("error", "fact", "decision"),
        graph_hops=2,
        prefer_vector=True,
        prefer_graph=True,
        time_filter=False,
        token_budget_fraction=0.75,
    ),
    QueryIntent.GENERAL: IntentRouting(
        intent=QueryIntent.GENERAL,
        boost_subtypes=("decision", "rule", "fact"),
        graph_hops=2,
        prefer_vector=True,
        prefer_graph=True,
        time_filter=False,
        token_budget_fraction=1.0,
    ),
}


def classify_intent(query: str) -> QueryIntent:
    """Cheap rules-based intent classification (no LLM)."""
    # Path / symbol location wins over debug keywords in the same query.
    if _PATH_HINT.search(query) or _LOCATE.search(query):
        if _IMPACT.search(query):
            return QueryIntent.IMPACT
        return QueryIntent.LOCATE
    if _IMPACT.search(query):
        return QueryIntent.IMPACT
    # Cause-seeking beats WHY: "why is X not firing" is a debug query, not a
    # decision query. WHY boosts decision/rule/fact and never surfaces error
    # neurons, which is exactly what symptom-side lookups need. Explicit
    # decision markers ("why did we choose X") keep their WHY routing.
    if (_DEBUG.search(query) or _SYMPTOM.search(query)) and not _DECISION_MARKER.search(query):
        return QueryIntent.DEBUG
    if _WHY.search(query):
        return QueryIntent.WHY
    if _TEMPORAL.search(query):
        return QueryIntent.TEMPORAL
    if _DEBUG.search(query):
        return QueryIntent.DEBUG
    return QueryIntent.GENERAL


def route_query(query: str) -> IntentRouting:
    return _ROUTING[classify_intent(query)]


def is_off_domain_query(query: str) -> bool:
    """True when the query looks personal / non-coding despite keyword overlap.

    Used to abstain on theme-leak prompts (e.g. wifi password mentioning a
    vendor name that also appears in project decisions).
    """
    return bool(_OFF_DOMAIN.search(query or ""))
