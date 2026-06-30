"""Task-specific context pack compiler — live DB, token-budgeted."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from brainkm.models.brain_config import BrainConfig
from brainkm.models.schemas import ContextPackResponse, NeuronResult
from brainkm.services.budget import (
    BudgetLine,
    context_pack_slots,
    greedy_truncate,
    line_tokens,
    priority_for,
    render_pack_section,
)
from brainkm.services.channel_health import graph_available
from brainkm.services.search import recall_with_bfs, traverse


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
                raw = json.loads(raw)
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


def compile_context_pack(
    conn: sqlite3.Connection,
    query: str,
    *,
    config: BrainConfig,
    project_dir: Path | None = None,
) -> ContextPackResponse:
    """Compile a bounded task pack from live brain.db."""
    slots = context_pack_slots(config, query)
    graph_ok = graph_available(conn)
    lines: list[BudgetLine] = []

    recall = recall_with_bfs(
        conn,
        query,
        graph=config.graph,
        recall=config.recall,
        project_dir=project_dir,
    )
    for ranked in recall.nodes:
        row = _node_row(conn, ranked.node_id)
        if row is None:
            continue
        line = _to_budget_line(row)
        line = BudgetLine(
            node_id=line.node_id,
            kind=line.kind,
            subtype=line.subtype,
            title=line.title,
            content=line.content,
            tokens=line.tokens,
            priority=min(line.priority, 4),
        )
        lines.append(line)

    graph_results: list[NeuronResult] = []
    if graph_ok:
        path_match = re.search(r"[\w./-]+\.(py|ts|tsx|js|go|rs)", query)
        seed = path_match.group(0) if path_match else query.split()[0] if query.split() else query
        traversal = traverse(
            conn,
            seed,
            max_hops=2,
            graph=config.graph,
        )
        for ranked in traversal.nodes[:10]:
            row = _node_row(conn, ranked.node_id)
            if row is None or row["kind"] != "code":
                continue
            lines.append(_to_budget_line(row))
            graph_results.append(_to_neuron_result(row, score=ranked.score))

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
        lines.append(_to_budget_line(row))

    max_tokens = min(config.budget.total_tokens, sum(slots.values()))
    included, manifest = greedy_truncate(lines, max_tokens=max_tokens)

    neuron_lines = [line for line in included if line.kind == "memory"]
    graph_lines = [line for line in included if line.kind == "code"]
    proc_lines = [line for line in included if line.kind == "procedure"]

    pack_parts = ["# Context pack", "", f"Query: {query}", ""]
    if not graph_ok:
        pack_parts.extend(["> Graph unavailable — FTS-only neighborhood.", ""])
    pack_parts.extend(render_pack_section("Decisions & facts", neuron_lines))
    pack_parts.extend(render_pack_section("Code neighborhood", graph_lines))
    pack_parts.extend(render_pack_section("Procedures", proc_lines))

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
        for line in neuron_lines
    ]

    return ContextPackResponse(
        query=query,
        pack_text=pack_text,
        neurons=neurons,
        graph_nodes=graph_results[: len(graph_lines)],
        truncation=manifest,
        graph_available=graph_ok,
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
    return compile_context_pack(conn, seed, config=config, project_dir=project_dir)
