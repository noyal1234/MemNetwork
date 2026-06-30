"""Token budget enforcement and truncation manifests."""

from __future__ import annotations

from dataclasses import dataclass

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


def recall_slots(config: BrainConfig) -> int:
    if config.budget.dynamic_reallocation:
        return min(400, config.budget.total_tokens // 3)
    return min(300, config.budget.session_start.recall_top)


def greedy_truncate(
    lines: list[BudgetLine],
    *,
    max_tokens: int,
) -> tuple[list[BudgetLine], TruncationManifest]:
    """Include highest-priority lines until token budget is exhausted."""
    if not lines:
        return [], TruncationManifest(token_budget=max_tokens, tokens_used=0)

    ordered = sorted(lines, key=lambda item: (item.priority, -item.tokens))
    included: list[BudgetLine] = []
    omitted: list[BudgetLine] = []
    used = 0

    for line in ordered:
        if used + line.tokens <= max_tokens or not included:
            if used + line.tokens > max_tokens and included:
                omitted.append(line)
                continue
            included.append(line)
            used += line.tokens
        else:
            omitted.append(line)

    return included, TruncationManifest(
        included_ids=[line.node_id for line in included],
        omitted_ids=[line.node_id for line in omitted],
        token_budget=max_tokens,
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
