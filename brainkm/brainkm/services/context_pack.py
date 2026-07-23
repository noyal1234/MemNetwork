"""Task-specific context pack compiler — live DB, token-budgeted."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from brainkm.models.brain_config import BrainConfig
from brainkm.models.schemas import ContextPackResponse, NeuronResult
from brainkm.services.budget import (
    MCP_JSON_OVERHEAD_TOKENS,
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
from brainkm.services.memory import token_count
from brainkm.services.quality import passes_stored_neuron_gate
from brainkm.services.search import (
    fts_search_nodes,
    recall_with_bfs,
    resolve_node_ref,
    traverse,
)

GRAPH_HINT = (
    "Graph available but no symbol/path resolved from query — "
    "retry with a symbol/path in the query or seed_refs. "
    "For pure call/import/blast-radius questions prefer traverse. "
    "Stale graphs auto-queue a refresh; or run `brainkm graph sync`."
)
MAX_QUERY_CHARS = 240
MAX_PACK_QUERY_TOKENS = 40


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
            for field in (
                "path",
                "file_path",
                "filePath",
                "target_file",
                "TargetFile",
                "AbsolutePath",
                "command",
                "CommandLine",
                "DirectoryPath",
                "SearchPath",
                "Url",
                "query",
            ):
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
    content = _display_content(row)
    return BudgetLine(
        node_id=row["id"],
        kind=row["kind"],
        subtype=row["subtype"],
        title=row["title"],
        content=content,
        tokens=line_tokens(row["title"], content),
        priority=priority_for(row["kind"], row["subtype"]),
    )


def _display_content(row: sqlite3.Row) -> str:
    """Format node content for packs — code nodes include path + location, not AST JSON."""
    raw = (row["content"] or "").strip()
    path = ""
    try:
        path = (row["path"] or "").strip()
    except (IndexError, KeyError):
        path = ""
    if row["kind"] != "code":
        return raw
    # Drop trailing Graphify extra JSON (`L54 | {"_origin": "ast"}`).
    location = raw.split(" | ", 1)[0].strip() if raw else ""
    if location.startswith("{"):
        location = ""
    parts = [p for p in (path, location) if p]
    return " — ".join(parts) if parts else raw


_POLICY_MARKERS = (
    "remember_neuron",
    "redact",
    "redaction",
    "supersede",
    "WriteQueue",
    "sanitize",
)


def _summarize_memory_content(content: str, subtype: str | None) -> str:
    """Summary-first with policy markers preserved for rule/decision neurons."""
    body = content.strip()
    if not body:
        return body
    if subtype in {"rule", "decision"} and token_count(body) <= 80:
        return body
    first_line = body.split("\n", 1)[0].strip()
    if len(first_line) > 160:
        first_line = first_line[:157] + "…"
    lower_body = body.lower()
    lower_first = first_line.lower()
    for marker in _POLICY_MARKERS:
        marker_lower = marker.lower()
        if marker_lower in lower_body and marker_lower not in lower_first:
            idx = lower_body.find(marker_lower)
            start = body.rfind(".", 0, idx) + 1
            end = body.find(".", idx + len(marker))
            clause = body[start : end if end > 0 else len(body)].strip()
            if clause:
                return f"{first_line} — {clause}"
    return first_line


def _to_neuron_result(row: sqlite3.Row, *, score: float | None = None) -> NeuronResult:
    path = None
    try:
        path = row["path"]
    except (IndexError, KeyError):
        path = None
    return NeuronResult(
        node_id=row["id"],
        kind=row["kind"],
        subtype=row["subtype"],
        title=row["title"],
        content=_display_content(row),
        score=score,
        path=path,
    )


def _cap_query_for_pack(query: str) -> str:
    text = query.strip()
    if len(text) > MAX_QUERY_CHARS:
        text = text[: MAX_QUERY_CHARS - 1].rstrip() + "…"
    # Ensure the echoed query itself stays small in tokens.
    while text and token_count(text) > MAX_PACK_QUERY_TOKENS:
        text = text[: max(0, len(text) - 20)].rstrip() + "…"
    return text


def _fit_pack_text(
    *,
    query_echo: str,
    pre_sections: list[str],
    neuron_kept: list[BudgetLine],
    graph_kept: list[BudgetLine],
    proc_kept: list[BudgetLine],
    omitted_ids: list[str],
    total_tokens: int,
) -> tuple[str, list[BudgetLine], list[BudgetLine], list[BudgetLine]]:
    """Assemble pack_text and drop lowest-priority lines until it fits total_tokens."""
    neurons = list(neuron_kept)
    graphs = list(graph_kept)
    procs = list(proc_kept)

    def build(omit_footer: bool = False) -> str:
        parts = ["# Context pack", "", f"Query: {query_echo}", ""]
        parts.extend(pre_sections)
        parts.extend(render_pack_section("Decisions & facts", neurons))
        parts.extend(render_pack_section("Code neighborhood", graphs))
        parts.extend(render_pack_section("Procedures", procs))
        if omitted_ids and not omit_footer:
            parts.extend(
                [
                    "## Truncated / expand",
                    "",
                    f"Omitted {len(omitted_ids)} nodes (token cap). "
                    "Expand a listed id via `recall` with `truncation_followup: true` "
                    "(summary-first packs use gists — expand before re-reading source).",
                    "",
                ]
            )
        return "\n".join(parts).rstrip() + "\n"

    pack_text = build()
    if token_count(pack_text) <= total_tokens:
        return pack_text, neurons, graphs, procs

    # Drop from the end of lowest-priority channel lists until under budget.
    pools = [procs, graphs, neurons]
    while any(pools) and token_count(pack_text) > total_tokens:
        for pool in pools:
            if pool:
                pool.pop()
                break
        pack_text = build()

    if token_count(pack_text) > total_tokens:
        pack_text = build(omit_footer=True)
    # Hard clip as last resort (should be rare).
    while token_count(pack_text) > total_tokens and len(pack_text) > 80:
        pack_text = pack_text[: int(len(pack_text) * 0.9)].rstrip() + "\n…"
    return pack_text, neurons, graphs, procs


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
        # Seeds are the query anchors — keep them even though traverse omits self.
        scored[seed_id] = max(scored.get(seed_id, 0.0), 1.0)
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
    include_structured: bool = False,
    summary_first: bool | None = None,
    extra_seed_ids: list[str] | None = None,
    include_sources: bool | None = None,
) -> ContextPackResponse:
    """Compile a bounded task pack from live brain.db."""
    from brainkm.adapters.redaction import sanitize_for_storage
    from brainkm.models.schemas import ProvenanceSource
    from brainkm.services.budget import adaptive_token_budget
    from brainkm.services.compress import dedup_budget_lines, mmr_diversify
    from brainkm.services.feedback import record_injected
    from brainkm.services.provenance import compact_sources_for_node

    use_summary = config.compression.summary_first if summary_first is None else summary_first
    effective_slots = slots or context_pack_slots(config, query)
    budget_cap = adaptive_token_budget(config, query)
    # Always respect budget_cap; custom slots must not widen the truncate pass.
    hard_cap = max(
        0,
        min(budget_cap, sum(effective_slots.values())) - PACK_FRAMING_OVERHEAD_TOKENS,
    )
    graph_ok = graph_available(conn)
    query_echo = _cap_query_for_pack(query)

    neuron_lines: list[BudgetLine] = []
    recall = recall_with_bfs(
        conn,
        query,
        graph=config.graph,
        recall=config.recall,
        semantic=config.semantic_config(),
        project_dir=project_dir,
        extra_seed_ids=extra_seed_ids,
    )
    code_seed_refs: list[str] = []
    for ranked in recall.nodes:
        row = _node_row(conn, ranked.node_id)
        if row is None or row["kind"] != "code":
            continue
        path = (row["path"] or "").strip()
        code_seed_refs.append(path if path else ranked.node_id)
    for ranked in recall.nodes:
        row = _node_row(conn, ranked.node_id)
        if row is None or row["kind"] != "memory":
            continue
        if not passes_stored_neuron_gate(title=row["title"] or "", content=row["content"]):
            continue
        # Outbound injection gate — same redaction rules as capture.
        # sanitize_for_storage reports via .blocked (it does not raise), so the
        # result must be checked explicitly or blocked content leaks into packs.
        gate = sanitize_for_storage(
            row["title"] or "",
            row["content"] or "",
            source="injection",
            mode="capture",
        )
        if gate.blocked:
            continue
        line = _to_budget_line(row)
        content = line.content
        if use_summary and content:
            content = _summarize_memory_content(content, row["subtype"])
        neuron_lines.append(
            BudgetLine(
                node_id=line.node_id,
                kind=line.kind,
                subtype=line.subtype,
                title=line.title,
                content=content,
                tokens=line_tokens(line.title, content),
                priority=min(line.priority, 4),
            )
        )

    if config.compression.pack_dedup:
        neuron_lines = dedup_budget_lines(
            neuron_lines,
            use_embeddings=config.semantic_enabled(),
        )
    if config.compression.pack_diversity:
        neuron_lines = mmr_diversify(neuron_lines)

    graph_lines: list[BudgetLine] = []
    graph_results: list[NeuronResult] = []
    graph_hint: str | None = None
    if graph_ok:
        merged_refs = list(seed_refs or []) + code_seed_refs
        seed_ids = _resolve_graph_seeds(
            conn,
            query,
            explicit=merged_refs or None,
        )
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
        SELECT id, kind, subtype, title, content, token_count, path
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
        included_by_id[line.node_id] for line in neuron_lines if line.node_id in included_ids
    ]
    graph_kept = [
        included_by_id[line.node_id] for line in graph_lines if line.node_id in included_ids
    ]
    proc_kept = [
        included_by_id[line.node_id] for line in proc_lines if line.node_id in included_ids
    ]
    graph_results = [node for node in graph_results if node.node_id in included_ids]

    pre_sections: list[str] = []
    if not graph_ok:
        pre_sections.extend(["> Graph unavailable — FTS-only neighborhood.", ""])
    elif graph_hint:
        pre_sections.extend([f"> {graph_hint}", ""])

    # Compact decision history (supersede chains) when query looks decision-shaped.
    from brainkm.services.decision_trail import (
        build_decision_trail,
        format_decision_history_section,
        should_include_history,
    )

    if should_include_history(
        include_history=None,
        intent=getattr(recall, "intent", None),
        query=query,
    ):
        decision_ids = [
            line.node_id
            for line in neuron_lines
            if (line.subtype or "") in {"decision", "rule", "fact"}
        ][:3]
        trail = build_decision_trail(conn, decision_ids, max_entries=8)
        history_lines = format_decision_history_section(trail)
        if history_lines:
            pre_sections.extend(history_lines)

    pack_text, neuron_kept, graph_kept, proc_kept = _fit_pack_text(
        query_echo=query_echo,
        pre_sections=pre_sections,
        neuron_kept=neuron_kept,
        graph_kept=graph_kept,
        proc_kept=proc_kept,
        omitted_ids=manifest.omitted_ids,
        total_tokens=max(
            100,
            budget_cap - MCP_JSON_OVERHEAD_TOKENS,
        ),
    )
    final_ids = {line.node_id for line in neuron_kept + graph_kept + proc_kept}
    try:
        record_injected(conn, [line.node_id for line in neuron_kept])
    except Exception:  # noqa: BLE001
        pass
    dropped = [nid for nid in manifest.included_ids if nid not in final_ids]
    if dropped:
        manifest = manifest.model_copy(
            update={
                "included_ids": [nid for nid in manifest.included_ids if nid in final_ids],
                "omitted_ids": list(manifest.omitted_ids) + dropped,
                "tokens_used": token_count(pack_text),
            }
        )
    else:
        manifest = manifest.model_copy(update={"tokens_used": token_count(pack_text)})

    neurons: list[NeuronResult] = []
    if include_structured:
        from brainkm.services.mcp_results import trim_neurons_to_budget

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
        graph_results = [node for node in graph_results if node.node_id in final_ids]
        # Structured arrays duplicate pack_text bodies — keep them within the
        # same agent-facing budget as lean pack_text.
        structured_budget = max(100, budget_cap - MCP_JSON_OVERHEAD_TOKENS)
        half = max(50, structured_budget // 2)
        neurons = trim_neurons_to_budget(neurons, budget=half)
        graph_results = trim_neurons_to_budget(graph_results, budget=structured_budget - half)
    else:
        graph_results = []
        # Keep truncation id lists short so the MCP JSON envelope stays budgeted.
        manifest = manifest.model_copy(
            update={
                "included_ids": list(manifest.included_ids)[:25],
                "omitted_ids": list(manifest.omitted_ids)[:15],
            }
        )

    sources: dict[str, list[ProvenanceSource]] = {}
    want_sources = include_sources if include_sources is not None else config.recall.include_sources
    if want_sources:
        for line in neuron_kept[:8]:
            compact = compact_sources_for_node(conn, line.node_id, max_links=3)
            if compact:
                sources[line.node_id] = [ProvenanceSource(**item) for item in compact]

    return ContextPackResponse(
        query=query_echo,
        pack_text=pack_text,
        neurons=neurons,
        graph_nodes=graph_results,
        truncation=manifest,
        graph_available=graph_ok,
        graph_hint=graph_hint,
        sources=sources,
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
