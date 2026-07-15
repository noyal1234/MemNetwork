"""MCP tool dispatch — thin handlers delegating to services."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from brainkm.db.connection import connect
from brainkm.db.paths import brain_db_path
from brainkm.models.brain_config import BrainConfig
from brainkm.models.schemas import (
    BrainStatsRequest,
    BrainStatsResponse,
    ContextPackRequest,
    ContextPackResponse,
    ForgetRequest,
    ForgetResponse,
    GraphSyncRequest,
    GraphSyncResponse,
    NeuronResult,
    RecallRequest,
    RecallResponse,
    RememberRequest,
    RememberResponse,
    SessionStatusRequest,
    SessionStatusResponse,
    TraverseRequest,
    TraverseResponse,
)
from brainkm.services.brain_stats import collect_brain_stats
from brainkm.services.config_loader import load_brain_config
from brainkm.services.context_pack import compile_context_pack
from brainkm.services.learning import persist_neuron_hits
from brainkm.services.mcp_results import (
    budget_session_chunk_excerpts,
    filter_active_memory_ids,
    ranked_to_neuron,
    trim_neurons_to_budget,
)
from brainkm.services.memory import forget_neuron, remember_neuron, token_count
from brainkm.services.recall import recall_live
from brainkm.services.recall_limit import get_recall_limit_state
from brainkm.services.remember_links import detect_conflicts, link_code_nodes_by_path
from brainkm.services.search import traverse
from brainkm.services.session_activity import (
    flush_stale_session_hits,
    prune_old_tool_use,
    record_mcp_tool_use,
)
from brainkm.services.session_status import get_session_status, set_session_status


@dataclass(frozen=True)
class BrainRuntime:
    project_dir: Path

    @property
    def config(self) -> BrainConfig:
        return load_brain_config(self.project_dir)


def _maintenance(conn: sqlite3.Connection) -> None:
    flush_stale_session_hits(conn)
    prune_old_tool_use(conn)


def handle_remember(
    conn: sqlite3.Connection,
    request: RememberRequest,
    *,
    config: BrainConfig | None = None,
) -> RememberResponse:
    cfg = config or BrainConfig()
    record = remember_neuron(
        conn,
        title=request.title,
        content=request.body,
        kind=request.kind,
        subtype=request.subtype,
        tags=request.tags,
        session_id=request.session_id,
        source="mcp_remember",
        compress=cfg.compression.write_time,
        max_body_tokens=cfg.compression.max_body_tokens,
        semantic_enabled=cfg.semantic_enabled(),
    )
    linked = link_code_nodes_by_path(
        conn,
        record.id,
        title=record.title,
        content=record.content or "",
    )
    suggestions = detect_conflicts(
        conn,
        title=record.title,
        content=record.content or "",
        exclude_id=record.id,
    )
    candidates = [s.node_id for s in suggestions]
    conflicts = [s.node_id for s in suggestions if s.conflict]
    record_mcp_tool_use(conn, request.session_id, "remember", result_count=1)
    _maintenance(conn)
    conn.commit()
    return RememberResponse(
        node_id=record.id,
        title=record.title,
        linked_code_nodes=linked,
        supersede_candidates=candidates,
        conflict_suggestions=conflicts,
    )


def handle_recall(
    conn: sqlite3.Connection,
    request: RecallRequest,
    *,
    config: BrainConfig,
    project_dir: Path,
) -> RecallResponse:
    limiter = get_recall_limit_state()
    if not limiter.check(
        request.session_id,
        config,
        truncation_followup=request.truncation_followup,
    ):
        record_mcp_tool_use(
            conn,
            request.session_id,
            "recall",
            abstained=True,
            result_count=0,
        )
        _maintenance(conn)
        conn.commit()
        return RecallResponse(query=request.query, nodes=[], abstained=True, source="rate_limited")

    result = recall_live(
        conn,
        request.query,
        limit=request.limit,
        graph=config.graph,
        recall=config.recall,
        semantic=config.semantic_config(),
        config=config,
        project_dir=project_dir,
    )
    nodes: list[NeuronResult] = []
    for ranked in result.nodes:
        neuron = ranked_to_neuron(conn, ranked)
        if neuron is not None:
            nodes.append(neuron)

    nodes = trim_neurons_to_budget(nodes, budget=config.budget.total_tokens)

    hit_ids = [node.node_id for node in nodes]
    persist_neuron_hits(
        conn,
        request.session_id,
        hit_ids,
        source="recall",
        cap=config.learning.session_window_size,
    )
    record_mcp_tool_use(
        conn,
        request.session_id,
        "recall",
        abstained=result.abstained,
        result_count=len(nodes),
    )
    _maintenance(conn)
    conn.commit()

    nodes_tokens = sum(
        token_count(f"{node.title}\n{node.content or ''}") for node in nodes
    )
    chunk_budget = max(0, config.budget.total_tokens - nodes_tokens)
    chunks = budget_session_chunk_excerpts(
        result.session_chunks,
        budget=chunk_budget,
    )

    return RecallResponse(
        query=result.query,
        nodes=nodes,
        abstained=result.abstained,
        source=result.source,
        session_chunks=chunks,
        intent=result.intent,
    )


def handle_context_pack(
    conn: sqlite3.Connection,
    request: ContextPackRequest,
    *,
    config: BrainConfig,
    project_dir: Path,
) -> ContextPackResponse:
    result = compile_context_pack(
        conn,
        request.query,
        config=config,
        project_dir=project_dir,
        seed_refs=request.seed_refs or None,
        include_structured=request.include_structured,
        summary_first=request.summary_first,
    )
    hit_ids = filter_active_memory_ids(conn, list(result.truncation.included_ids))
    persist_neuron_hits(
        conn,
        request.session_id,
        hit_ids,
        source="context_pack",
        cap=config.learning.session_window_size,
    )
    record_mcp_tool_use(
        conn,
        request.session_id,
        "context_pack",
        result_count=len(result.truncation.included_ids),
    )
    _maintenance(conn)
    conn.commit()
    return result


def handle_session_status(
    conn: sqlite3.Connection,
    request: SessionStatusRequest,
) -> SessionStatusResponse:
    if request.title is not None and request.body is not None:
        record = set_session_status(
            conn,
            title=request.title,
            body=request.body,
            session_id=request.session_id,
        )
        record_mcp_tool_use(conn, request.session_id, "session_status", result_count=1)
        _maintenance(conn)
        conn.commit()
        return SessionStatusResponse(
            node_id=record.id,
            title=record.title,
            body=record.content,
            updated=True,
        )

    record = get_session_status(conn, session_id=request.session_id)
    record_mcp_tool_use(
        conn,
        request.session_id,
        "session_status",
        result_count=1 if record else 0,
    )
    _maintenance(conn)
    conn.commit()
    if record is None:
        return SessionStatusResponse()
    return SessionStatusResponse(
        node_id=record.id,
        title=record.title,
        body=record.content,
        updated=False,
    )


def handle_traverse(
    conn: sqlite3.Connection,
    request: TraverseRequest,
    *,
    config: BrainConfig,
) -> TraverseResponse:
    result = traverse(
        conn,
        request.from_ref,
        to_ref=request.to_ref,
        max_hops=request.max_hops,
        relationship=request.relationship,
        direction=request.direction,
        graph=config.graph,
    )
    nodes: list[NeuronResult] = []
    for ranked in result.nodes:
        neuron = ranked_to_neuron(conn, ranked)
        if neuron is not None:
            nodes.append(neuron)
    nodes = trim_neurons_to_budget(nodes, budget=config.budget.total_tokens)
    record_mcp_tool_use(conn, None, "traverse", result_count=len(nodes))
    _maintenance(conn)
    conn.commit()
    return TraverseResponse(
        from_ref=request.from_ref,
        nodes=nodes,
        hops_explored=result.hops_explored,
    )


def handle_forget(conn: sqlite3.Connection, request: ForgetRequest) -> ForgetResponse:
    archived = forget_neuron(conn, request.node_id, reason=request.reason)
    record_mcp_tool_use(conn, None, "forget", result_count=1 if archived.valid_until else 0)
    _maintenance(conn)
    conn.commit()
    return ForgetResponse(
        node_id=archived.id,
        archived=archived.valid_until is not None,
        valid_until=archived.valid_until,
    )


def handle_brain_stats(
    conn: sqlite3.Connection,
    request: BrainStatsRequest,
    *,
    config: BrainConfig,
    project_dir: Path,
) -> BrainStatsResponse:
    record_mcp_tool_use(conn, request.session_id, "brain_stats", result_count=1)
    _maintenance(conn)
    conn.commit()
    return collect_brain_stats(
        conn,
        config=config,
        project_dir=project_dir,
        session_id=request.session_id,
    )


def handle_graph_sync(
    project_dir: Path,
    request: GraphSyncRequest,
    *,
    config: BrainConfig,
) -> GraphSyncResponse:
    from brainkm.services.graphify_sync import request_graph_sync, sync_graph

    if not request.force:
        request_graph_sync(project_dir)
        return GraphSyncResponse(
            requested=True,
            ran=False,
            ok=True,
            message="graph sync requested; MCP scheduler will run after debounce",
        )

    result = sync_graph(
        project_dir=project_dir,
        config=config,
        extract=not request.skip_extract,
        force=True,
    )
    ok_statuses = {"completed", "ok", "skipped_empty", "skipped", "skipped_locked"}
    status_ok = result.status in ok_statuses
    nodes = result.import_result.node_count if result.import_result else None
    edges = result.import_result.edge_count if result.import_result else None
    return GraphSyncResponse(
        requested=False,
        ran=True,
        ok=status_ok and result.status not in {"extract_failed", "missing_graph"},
        message=result.message or result.status,
        nodes_imported=nodes,
        edges_imported=edges,
    )


def _write_op(runtime: BrainRuntime, fn, *args, **kwargs) -> Any:
    conn = connect(brain_db_path(runtime.project_dir))
    try:
        result = fn(conn, *args, **kwargs)
        return result
    finally:
        conn.close()


async def _run_write(runtime: BrainRuntime, fn, *args, **kwargs) -> Any:
    """Serialize all DB-touching MCP handlers through the single-writer queue."""
    from brainkm.services.write_queue import get_write_queue

    queue = get_write_queue()
    return await queue.run(_write_op, runtime, fn, *args, **kwargs)


async def dispatch_tool(name: str, arguments: dict[str, Any], runtime: BrainRuntime) -> dict[str, Any]:
    """Route MCP tool call to the appropriate handler."""
    config = runtime.config

    if name == "remember":
        request = RememberRequest.model_validate(arguments)
        result = await _run_write(runtime, handle_remember, request, config=config)
        return result.model_dump()

    if name == "recall":
        request = RecallRequest.model_validate(arguments)
        result = await _run_write(
            runtime,
            handle_recall,
            request,
            config=config,
            project_dir=runtime.project_dir,
        )
        return result.model_dump()

    if name == "context_pack":
        request = ContextPackRequest.model_validate(arguments)
        result = await _run_write(
            runtime,
            handle_context_pack,
            request,
            config=config,
            project_dir=runtime.project_dir,
        )
        return result.model_dump()

    if name == "session_status":
        request = SessionStatusRequest.model_validate(arguments)
        result = await _run_write(runtime, handle_session_status, request)
        return result.model_dump()

    if name == "traverse":
        request = TraverseRequest.model_validate(arguments)
        result = await _run_write(runtime, handle_traverse, request, config=config)
        return result.model_dump()

    if name == "forget":
        request = ForgetRequest.model_validate(arguments)
        result = await _run_write(runtime, handle_forget, request)
        return result.model_dump()

    if name == "brain_stats":
        request = BrainStatsRequest.model_validate(arguments or {})
        result = await _run_write(
            runtime,
            handle_brain_stats,
            request,
            config=config,
            project_dir=runtime.project_dir,
        )
        return result.model_dump()

    if name == "graph_sync":
        request = GraphSyncRequest.model_validate(arguments or {})

        def _log_and_sync(conn: sqlite3.Connection) -> GraphSyncResponse:
            record_mcp_tool_use(conn, None, "graph_sync", result_count=1 if request.force else 0)
            _maintenance(conn)
            conn.commit()
            return handle_graph_sync(runtime.project_dir, request, config=config)

        result = await _run_write(runtime, _log_and_sync)
        return result.model_dump()

    msg = f"unknown tool: {name}"
    raise ValueError(msg)
