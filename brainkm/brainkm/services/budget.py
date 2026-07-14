"""Token budget enforcement and truncation manifests."""

from __future__ import annotations

from dataclasses import dataclass, replace

from brainkm.models.brain_config import BrainConfig
from brainkm.models.schemas import TruncationManifest
from brainkm.services.memory import token_count

SUBTYPE_PRIORITY: dict[tuple[str, str | None], int] = {
    ("memory", "decision"): 0,
    ("memory", "error"): 1,
    ("memory", "rule"): 2,
    ("memory", "fact"): 3,
    ("memory", "pattern"): 4,
    ("memory", "context"): 5,
    ("procedure", None): 6,
    ("procedure", "workflow"): 6,
    ("code", "file"): 7,
    ("code", "class"): 8,
    ("code", "function"): 9,
    ("tool", None): 10,
    ("session", None): 11,
}
DEFAULT_PRIORITY = 12

# Reserved for pack headers, query line, graph hints, truncation footer in context_pack.
PACK_FRAMING_OVERHEAD_TOKENS = 50


@dataclass(frozen=True)
class BudgetLine:
    node_id: str
    kind: str
    subtype: str | None
    title: str
    content: str
    tokens: int
    priority: int


def priority_for(kind: str, subtype: str | None) -> int:
    return SUBTYPE_PRIORITY.get((kind, subtype), SUBTYPE_PRIORITY.get((kind, None), DEFAULT_PRIORITY))


def line_tokens(title: str, content: str | None, stored: int | None = None) -> int:
    if stored is not None and stored > 0:
        return stored
    return token_count(f"{title}\n{content or ''}")


def classify_query_type(query: str) -> str:
    lowered = query.lower()
    if any(ext in query for ext in (".py", ".ts", ".tsx", ".js", ".go", ".rs")):
        return "code"
    if any(word in lowered for word in ("error", "bug", "fix", "fail", "broken")):
        return "debug"
    if any(word in lowered for word in ("decide", "policy", "rule", "architecture")):
        return "decision"
    return "general"


def context_pack_slots(config: BrainConfig, query: str | None = None) -> dict[str, int]:
    """Allocate token slots for context_pack; reallocate by query type when enabled."""
    total = config.budget.total_tokens
    pre = config.budget.pre_tool
    query_type = classify_query_type(query or "")

    if config.budget.dynamic_reallocation:
        if query_type == "code":
            graph = min(pre.graph_neighborhood, int(total * 0.45))
            neurons = max(200, total - graph - min(pre.procedure_expanded, total // 5))
            procedures = total - graph - neurons
        elif query_type == "debug":
            neurons = min(600, int(total * 0.55))
            graph = min(pre.graph_neighborhood, int(total * 0.25))
            procedures = total - graph - neurons
        elif query_type == "decision":
            neurons = min(700, int(total * 0.6))
            graph = min(pre.graph_neighborhood, int(total * 0.2))
            procedures = total - graph - neurons
        else:
            graph = min(pre.graph_neighborhood, total // 2)
            procedures = min(pre.procedure_expanded, total // 4)
            neurons = max(200, total - graph - procedures)
        return {"neurons": neurons, "graph": graph, "procedures": procedures}

    return {
        "neurons": min(500, total // 2),
        "graph": min(pre.graph_neighborhood, total // 3),
        "procedures": min(pre.procedure_expanded, total // 4),
    }


def _fit_line_to_budget(line: BudgetLine, max_tokens: int) -> BudgetLine:
    """Shrink content so title+content fits within max_tokens (tiktoken)."""
    if max_tokens <= 0:
        return replace(line, content="", tokens=0)
    if line.tokens <= max_tokens:
        return line

    title_cost = token_count(line.title) + 1  # account for newline separator
    body_budget = max(0, max_tokens - title_cost)
    if body_budget <= 0:
        fitted_tokens = token_count(line.title)
        if fitted_tokens <= max_tokens:
            return replace(line, content="", tokens=fitted_tokens)
        return replace(line, content="", tokens=0)

    content = line.content or ""
    lo, hi = 0, len(content)
    best = ""
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = content[:mid]
        if token_count(candidate) <= body_budget:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1
    fitted = best.rstrip()
    if fitted and fitted != content:
        fitted = fitted + "…"
    tokens = token_count(f"{line.title}\n{fitted}" if fitted else line.title)
    while tokens > max_tokens and fitted:
        fitted = fitted[:-2].rstrip()
        if fitted:
            fitted = fitted + "…"
        tokens = token_count(f"{line.title}\n{fitted}" if fitted else line.title)
    if tokens > max_tokens:
        title_only = token_count(line.title)
        if title_only <= max_tokens:
            return replace(line, content="", tokens=title_only)
        return replace(line, content="", tokens=0)
    return replace(line, content=fitted, tokens=tokens)


def greedy_truncate(
    lines: list[BudgetLine],
    *,
    max_tokens: int,
) -> tuple[list[BudgetLine], TruncationManifest]:
    """Include highest-priority lines until token budget is exhausted.

    Oversized lines are content-truncated to fit rather than exceeding the cap.
    """
    if not lines:
        return [], TruncationManifest(token_budget=max_tokens, tokens_used=0)
    if max_tokens <= 0:
        return [], TruncationManifest(
            omitted_ids=[line.node_id for line in lines],
            token_budget=max_tokens,
            tokens_used=0,
        )

    ordered = sorted(lines, key=lambda item: (item.priority, -item.tokens))
    included: list[BudgetLine] = []
    omitted: list[BudgetLine] = []
    used = 0

    for line in ordered:
        remaining = max_tokens - used
        if remaining <= 0:
            omitted.append(line)
            continue
        if line.tokens <= remaining:
            included.append(line)
            used += line.tokens
            continue
        # Only the first included item may be content-truncated to enforce the hard cap;
        # later oversized items are omitted (leftover may reallocate across channels).
        if not included:
            fitted = _fit_line_to_budget(line, remaining)
            if fitted.tokens <= 0:
                omitted.append(line)
                continue
            included.append(fitted)
            used += fitted.tokens
        else:
            omitted.append(line)

    return included, TruncationManifest(
        included_ids=[line.node_id for line in included],
        omitted_ids=[line.node_id for line in omitted],
        token_budget=max_tokens,
        tokens_used=used,
    )


CHANNEL_ORDER = ("neurons", "graph", "procedures")


def pre_tool_pack_slots(config: BrainConfig) -> dict[str, int]:
    """Bounded slots for PreToolUse injection (prefer graph neighborhood)."""
    graph = config.budget.pre_tool.graph_neighborhood
    procedures = config.budget.pre_tool.procedure_expanded
    neurons = min(200, config.budget.session_start.recall_top)
    return {"neurons": neurons, "graph": graph, "procedures": procedures}


def truncate_by_channels(
    channels: dict[str, list[BudgetLine]],
    slots: dict[str, int],
    *,
    dynamic_reallocation: bool = True,
    hard_cap: int | None = None,
) -> tuple[list[BudgetLine], TruncationManifest]:
    """Truncate each channel against its slot, then optionally reallocate unused budget."""
    included_by: dict[str, list[BudgetLine]] = {}
    omitted_by: dict[str, list[BudgetLine]] = {}
    used_by: dict[str, int] = {}
    total_slot = 0

    for channel in CHANNEL_ORDER:
        slot = max(0, slots.get(channel, 0))
        total_slot += slot
        included, manifest = greedy_truncate(channels.get(channel, []), max_tokens=slot)
        included_by[channel] = included
        omitted_ids = set(manifest.omitted_ids)
        omitted_by[channel] = [
            line for line in channels.get(channel, []) if line.node_id in omitted_ids
        ]
        used_by[channel] = manifest.tokens_used

    if dynamic_reallocation:
        leftover = sum(max(0, slots.get(ch, 0) - used_by[ch]) for ch in CHANNEL_ORDER)
        for channel in CHANNEL_ORDER:
            if leftover <= 0:
                break
            if not omitted_by[channel]:
                continue
            extra, extra_manifest = greedy_truncate(omitted_by[channel], max_tokens=leftover)
            if not extra:
                continue
            included_by[channel].extend(extra)
            used_by[channel] += extra_manifest.tokens_used
            leftover -= extra_manifest.tokens_used
            kept = {line.node_id for line in extra}
            omitted_by[channel] = [
                line for line in omitted_by[channel] if line.node_id not in kept
            ]

    included: list[BudgetLine] = []
    for channel in CHANNEL_ORDER:
        included.extend(included_by[channel])

    budget = hard_cap if hard_cap is not None else total_slot
    if hard_cap is not None and sum(line.tokens for line in included) > hard_cap:
        included, _ = greedy_truncate(included, max_tokens=hard_cap)
        kept = {line.node_id for line in included}
        for channel in CHANNEL_ORDER:
            omitted_by[channel].extend(
                line for line in included_by[channel] if line.node_id not in kept
            )
            included_by[channel] = [line for line in included_by[channel] if line.node_id in kept]

    omitted: list[BudgetLine] = []
    for channel in CHANNEL_ORDER:
        omitted.extend(omitted_by[channel])

    used = sum(line.tokens for line in included)
    return included, TruncationManifest(
        included_ids=[line.node_id for line in included],
        omitted_ids=[line.node_id for line in omitted],
        token_budget=budget,
        tokens_used=used,
    )


def render_pack_section(heading: str, lines: list[BudgetLine]) -> list[str]:
    if not lines:
        return []
    out = [f"## {heading}", ""]
    for line in lines:
        body = line.content.strip()
        label = line.subtype or line.kind
        if body:
            out.append(f"- **{line.title}** ({label}): {body}")
        else:
            out.append(f"- **{line.title}** ({label})")
    out.append("")
    return out
