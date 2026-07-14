"""Task-specific context pack compiler — live DB, token-budgeted."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from brainkm.models.brain_config import BrainConfig
from brainkm.models.schemas import ContextPackResponse, NeuronResult
from brainkm.services.budget import (
    PACK_FRAMING_OVERHEAD_TOKENS,
    BudgetLine,
    context_pack_slots,
    line_tokens,
    pre_tool_pack_slots,
    priority_for,
    render_pack_section,
    truncate_by_channels,
)
from brainkm.services.channel_health import graph_available
from brainkm.services.search import (
    fts_search_nodes,
    recall_with_bfs,
    resolve_node_ref,
    traverse,
)

GRAPH_HINT = (
    "Graph available but no symbol/path resolved from query — "
    "retry with a symbol name or file path, or call traverse directly."
)

_PATH_RE = re.compile(r"[\w./\-]+\.(?:py|ts|tsx|js|go|rs)\b")
_BACKTICK_RE = re.compile(r"`([^`]+)`")
_DOTTED_RE = re.compile(r"\b([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)+)\b")
_CAMEL_RE = re.compile(r"\b([A-Z][a-z0-9]+(?:[A-Z][a-zA-Z0-9]*)+)\b")
_SNAKE_RE = re.compile(r"\b([a-z_][a-z0-9_]{2,})\b")

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "if",
        "then",
        "else",
        "when",
        "where",
        "what",
        "which",
        "who",
        "whom",
        "how",
        "why",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "can",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "from",
        "with",
        "by",
        "about",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "under",
        "again",
        "further",
        "once",
        "here",
        "there",
        "all",
        "each",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "just",
        "this",
        "that",
        "these",
        "those",
        "i",
        "me",
        "my",
        "we",
        "our",
        "you",
        "your",
        "he",
        "she",
        "it",
        "they",
        "them",
        "their",
        "use",
        "using",
        "used",
        "via",
        "over",
        "code",
        "file",
        "files",
        "function",
        "functions",
        "class",
        "classes",
        "module",
        "modules",
        "show",
        "find",
        "get",
        "set",
        "call",
        "calls",
        "import",
        "imports",
        "please",
        "help",
        "need",
        "want",
        "make",
        "does",
        "work",
        "works",
        "working",
        "connect",
        "connects",
        "related",
        "around",
        "explain",
        "flow",
        "change",
        "changing",
        "edit",
        "editing",
        "break",
        "breaks",
    }
)

_MAX_SEEDS = 3
_MAX_GRAPH_NODES = 10


def extract_seed_candidates(
    query: str,
    *,
    explicit: list[str] | None = None,
) -> list[str]:
    """Extract symbol/path candidates for graph seeding from a natural-language query."""
    candidates: list[str] = []
    seen: set[str] = set()

    def add(ref: str) -> None:
        cleaned = ref.strip().strip("`'\"")
        if not cleaned or cleaned in seen:
            return
        if cleaned.lower() in _STOPWORDS:
            return
        if len(cleaned) < 2:
            return
        seen.add(cleaned)
        candidates.append(cleaned)

    for ref in explicit or ():
        add(ref)

    for match in _PATH_RE.finditer(query):
        add(match.group(0))
    for match in _BACKTICK_RE.finditer(query):
        add(match.group(1))
    for match in _DOTTED_RE.finditer(query):
        add(match.group(1))
    for match in _CAMEL_RE.finditer(query):
        add(match.group(1))
    for match in _SNAKE_RE.finditer(query):
        token = match.group(1)
        if "_" in token or len(token) >= 4:
            add(token)

    return candidates


def derive_pre_tool_query(payload: dict[str, object]) -> str | None:
    """Build a context_pack seed from PreToolUse hook payload; None when no meaningful seed."""
    for key in ("tool_input", "toolInput", "arguments", "input", "params"):
        raw = payload.get(key)
        if raw is None:
            continue
        if isinstance(raw, str):
            text = raw.strip()
            if len(text) >= 8:
                return text[:500]
            try:
                raw = json.loads(text)
            except json.JSONDecodeError:
                continue
        if isinstance(raw, dict):
            parts: list[str] = []
            for field in ("path", "file_path", "filePath", "target_file", "command", "query"):
                value = raw.get(field)
                if value is not None and str(value).strip():
                    parts.append(str(value).strip())
            if parts:
                return " ".join(parts)[:500]

    tool_name = payload.get("tool_name") or payload.get("toolName") or payload.get("tool")
    if tool_name is not None:
        name = str(tool_name).strip()
        if len(name) >= 8:
            return name
    return None


def _node_row(conn: sqlite3.Connection, node_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT id, kind, subtype, title, content, token_count, path
        FROM nodes
        WHERE id = ? AND valid_until IS NULL
        """,
        (node_id,),
    ).fetchone()


def _to_budget_line(row: sqlite3.Row) -> BudgetLine:
    return BudgetLine(
        node_id=row["id"],
        kind=row["kind"],
        subtype=row["subtype"],
        title=row["title"],
        content=row["content"] or "",
        tokens=line_tokens(row["title"], row["content"], row["token_count"]),
        priority=priority_for(row["kind"], row["subtype"]),
    )


def _to_neuron_result(row: sqlite3.Row, *, score: float | None = None) -> NeuronResult:
    return NeuronResult(
        node_id=row["id"],
        kind=row["kind"],
        subtype=row["subtype"],
        title=row["title"],
        content=row["content"],
        score=score,
    )


def _fts_code_seed_ids(conn: sqlite3.Connection, query: str, *, limit: int = 3) -> list[str]:
    """BM25 hits filtered to kind=code — structural fallback, not embeddings."""
    hits = fts_search_nodes(conn, query, limit=max(limit * 4, 8))
    out: list[str] = []
    for node_id, _score in hits:
        row = _node_row(conn, node_id)
        if row is None or row["kind"] != "code":
            continue
        out.append(node_id)
        if len(out) >= limit:
            break
    return out


def _resolve_graph_seeds(
    conn: sqlite3.Connection,
    query: str,
    *,
    explicit: list[str] | None = None,
) -> list[str]:
    """Resolve up to _MAX_SEEDS node ids from candidates, then FTS code fallback."""
    resolved: list[str] = []
    seen: set[str] = set()

    def add_id(node_id: str | None) -> None:
        if node_id and node_id not in seen:
            seen.add(node_id)
            resolved.append(node_id)

    for candidate in extract_seed_candidates(query, explicit=explicit):
        add_id(resolve_node_ref(conn, candidate))
        if len(resolved) >= _MAX_SEEDS:
            return resolved

    if not resolved:
        for node_id in _fts_code_seed_ids(conn, query, limit=_MAX_SEEDS):
            add_id(node_id)

    return resolved


def _collect_graph_neighborhood(
    conn: sqlite3.Connection,
    seed_ids: list[str],
    *,
    config: BrainConfig,
) -> tuple[list[BudgetLine], list[NeuronResult]]:
    """Traverse up to 2 hops from each seed; merge and dedupe by node id."""
    scored: dict[str, float] = {}
    for seed_id in seed_ids:
        traversal = traverse(
            conn,
            seed_id,
            max_hops=2,
            direction="both",
            graph=config.graph,
        )
        for ranked in traversal.nodes:
            prev = scored.get(ranked.node_id)
            if prev is None or ranked.score > prev:
                scored[ranked.node_id] = ranked.score

    ordered = sorted(scored.items(), key=lambda item: item[1], reverse=True)
    lines: list[BudgetLine] = []
    results: list[NeuronResult] = []
    for node_id, score in ordered[:_MAX_GRAPH_NODES]:
        row = _node_row(conn, node_id)
        if row is None or row["kind"] != "code":
            continue
        lines.append(_to_budget_line(row))
        results.append(_to_neuron_result(row, score=score))
    return lines, results


def compile_context_pack(
    conn: sqlite3.Connection,
    query: str,
    *,
    config: BrainConfig,
    project_dir: Path | None = None,
    seed_refs: list[str] | None = None,
    slots: dict[str, int] | None = None,
) -> ContextPackResponse:
    """Compile a bounded task pack from live brain.db."""
    effective_slots = slots or context_pack_slots(config, query)
    if slots is None:
        hard_cap = max(0, config.budget.total_tokens - PACK_FRAMING_OVERHEAD_TOKENS)
    else:
        hard_cap = max(0, sum(effective_slots.values()) - PACK_FRAMING_OVERHEAD_TOKENS)
    graph_ok = graph_available(conn)

    neuron_lines: list[BudgetLine] = []
    recall = recall_with_bfs(
        conn,
        query,
        graph=config.graph,
        recall=config.recall,
        project_dir=project_dir,
    )
    for ranked in recall.nodes:
        row = _node_row(conn, ranked.node_id)
        if row is None or row["kind"] != "memory":
            continue
        line = _to_budget_line(row)
        neuron_lines.append(
            BudgetLine(
                node_id=line.node_id,
                kind=line.kind,
                subtype=line.subtype,
                title=line.title,
                content=line.content,
                tokens=line.tokens,
                priority=min(line.priority, 4),
            )
        )

    graph_lines: list[BudgetLine] = []
    graph_results: list[NeuronResult] = []
    graph_hint: str | None = None
    if graph_ok:
        seed_ids = _resolve_graph_seeds(conn, query, explicit=seed_refs)
        if seed_ids:
            graph_lines, graph_results = _collect_graph_neighborhood(
                conn,
                seed_ids,
                config=config,
            )
        else:
            graph_hint = GRAPH_HINT

    proc_lines: list[BudgetLine] = []
    proc_rows = conn.execute(
        """
        SELECT id, kind, subtype, title, content, token_count
        FROM nodes
        WHERE valid_until IS NULL AND kind = 'procedure'
        ORDER BY use_count DESC, updated_at DESC
        LIMIT 5
        """
    ).fetchall()
    for row in proc_rows:
        proc_lines.append(_to_budget_line(row))

    channels = {
        "neurons": neuron_lines,
        "graph": graph_lines,
        "procedures": proc_lines,
    }
    included, manifest = truncate_by_channels(
        channels,
        effective_slots,
        dynamic_reallocation=config.budget.dynamic_reallocation,
        hard_cap=hard_cap,
    )
    included_by_id = {line.node_id: line for line in included}
    included_ids = set(included_by_id)

    # Prefer truncated content from the budget pass.
    neuron_kept = [
        included_by_id[line.node_id]
        for line in neuron_lines
        if line.node_id in included_ids
    ]
    graph_kept = [
        included_by_id[line.node_id]
        for line in graph_lines
        if line.node_id in included_ids
    ]
    proc_kept = [
        included_by_id[line.node_id]
        for line in proc_lines
        if line.node_id in included_ids
    ]
    graph_results = [node for node in graph_results if node.node_id in included_ids]

    pack_parts = ["# Context pack", "", f"Query: {query}", ""]
    if not graph_ok:
        pack_parts.extend(["> Graph unavailable — FTS-only neighborhood.", ""])
    elif graph_hint:
        pack_parts.extend([f"> {graph_hint}", ""])
    pack_parts.extend(render_pack_section("Decisions & facts", neuron_kept))
    pack_parts.extend(render_pack_section("Code neighborhood", graph_kept))
    pack_parts.extend(render_pack_section("Procedures", proc_kept))

    if manifest.omitted_ids:
        pack_parts.extend(
            [
                "## Truncated",
                "",
                f"Omitted {len(manifest.omitted_ids)} nodes (token cap). "
                "Call `recall` with `truncation_followup: true` for omitted IDs.",
                "",
            ]
        )

    pack_text = "\n".join(pack_parts).rstrip() + "\n"
    neurons = [
        NeuronResult(
            node_id=line.node_id,
            kind=line.kind,
            subtype=line.subtype,
            title=line.title,
            content=line.content,
        )
        for line in neuron_kept
    ]

    return ContextPackResponse(
        query=query,
        pack_text=pack_text,
        neurons=neurons,
        graph_nodes=graph_results,
        truncation=manifest,
        graph_available=graph_ok,
        graph_hint=graph_hint,
    )


def compile_pre_tool_pack(
    conn: sqlite3.Connection,
    payload: dict[str, object],
    *,
    config: BrainConfig,
    project_dir: Path | None = None,
) -> ContextPackResponse | None:
    seed = derive_pre_tool_query(payload)
    if seed is None:
        return None
    slots = pre_tool_pack_slots(config)
    return compile_context_pack(
        conn,
        seed,
        config=config,
        project_dir=project_dir,
        slots=slots,
    )
