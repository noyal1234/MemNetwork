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
    ProvenanceSource,
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
from brainkm.services.confidence import score_confidence
from brainkm.services.config_loader import load_brain_config
from brainkm.services.context_pack import compile_context_pack
from brainkm.services.decision_trail import build_decision_trail, should_include_history
from brainkm.services.impact import linked_memories_for_code_nodes
from brainkm.services.learning import persist_neuron_hits
from brainkm.services.mcp_results import (
    budget_session_chunk_excerpts,
    filter_active_memory_ids,
    ranked_to_neuron,
    trim_neurons_to_budget,
)
from brainkm.services.memory import forget_neuron, remember_neuron, supersede_neuron, token_count
from brainkm.services.neuron_index import index_neuron_links
from brainkm.services.provenance import compact_sources_for_node
from brainkm.services.recall import recall_live
from brainkm.services.recall_limit import get_recall_limit_state
from brainkm.services.remember_links import detect_conflicts
from brainkm.services.search import traverse
from brainkm.services.session_activity import (
    flush_stale_session_hits,
    load_file_seeds,
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


def _maybe_queue_graph_sync(
    project_dir: Path,
    config: BrainConfig,
    *,
    existing_hint: str | None = None,
) -> str | None:
    """If the code graph is stale, queue a background sync and annotate the hint."""
    if not config.graphify.enabled or not config.graphify.auto_sync.enabled:
        return existing_hint
    try:
        from brainkm.services.graphify_sync import (
            _graph_json_path,
            graph_json_newer_than_import,
            request_graph_sync,
        )
    except Exception:  # noqa: BLE001
        return existing_hint

    graph_path = _graph_json_path(project_dir, config)
    if not graph_path.is_file():
        return existing_hint
    try:
        stale = graph_json_newer_than_import(project_dir, config)
    except Exception:  # noqa: BLE001
        return existing_hint
    if not stale:
        return existing_hint
    request_graph_sync(project_dir)
    refresh = "graph refresh queued"
    if existing_hint:
        return f"{existing_hint} ({refresh})"
    return refresh


def handle_remember(
    conn: sqlite3.Connection,
    request: RememberRequest,
    *,
    config: BrainConfig | None = None,
) -> RememberResponse:
    cfg = config or BrainConfig()

    if request.action == "archive":
        assert request.target_node_id is not None
        archived = forget_neuron(
            conn,
            request.target_node_id,
            reason=request.reason or "remember action=archive",
        )
        record_mcp_tool_use(conn, request.session_id, "remember", result_count=1)
        _maintenance(conn)
        conn.commit()
        return RememberResponse(
            node_id=archived.id,
            title=archived.title,
            archived_node_id=archived.id,
            action="archive",
        )

    assert request.title is not None and request.body is not None
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
    linked = index_neuron_links(
        conn,
        record.id,
        title=record.title,
        content=record.content or "",
        tags=request.tags,
        kind=request.kind,
    )
    suggestions = detect_conflicts(
        conn,
        title=record.title,
        content=record.content or "",
        exclude_id=record.id,
    )
    candidates = [s.node_id for s in suggestions]
    conflicts = [s.node_id for s in suggestions if s.conflict]

    superseded_node_id: str | None = None
    if request.action == "correct":
        assert request.target_node_id is not None
        supersede_neuron(
            conn,
            request.target_node_id,
            replacement=record,
            reasoning=request.reason,
        )
        superseded_node_id = request.target_node_id
    elif (
        cfg.capture.auto_supersede_conflicts
        and conflicts
        and suggestions
        and suggestions[0].conflict
        and suggestions[0].similarity >= 0.9
    ):
        try:
            supersede_neuron(
                conn,
                suggestions[0].node_id,
                replacement=record,
                reasoning="auto_supersede_conflicts",
            )
            superseded_node_id = suggestions[0].node_id
        except ValueError:
            superseded_node_id = None

    record_mcp_tool_use(conn, request.session_id, "remember", result_count=1)
    _maintenance(conn)
    conn.commit()
    return RememberResponse(
        node_id=record.id,
        title=record.title,
        linked_code_nodes=linked,
        supersede_candidates=candidates,
        conflict_suggestions=conflicts,
        superseded_node_id=superseded_node_id,
        action=request.action,
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
        return RecallResponse(
            query=request.query,
            nodes=[],
            abstained=True,
            source="rate_limited",
            confidence="low",
        )

    result = recall_live(
        conn,
        request.query,
        limit=request.limit,
        graph=config.graph,
        recall=config.recall,
        semantic=config.semantic_config(),
        config=config,
        project_dir=project_dir,
        extra_seed_ids=list(load_file_seeds(conn, request.session_id)),
    )
    nodes: list[NeuronResult] = []
    for ranked in result.nodes:
        neuron = ranked_to_neuron(conn, ranked)
        if neuron is not None:
            nodes.append(neuron)

    nodes = trim_neurons_to_budget(nodes, budget=config.budget.total_tokens)

    want_sources = (
        request.include_sources
        if request.include_sources is not None
        else config.recall.include_sources
    )
    sources: dict[str, list[ProvenanceSource]] = {}
    if want_sources:
        for node in nodes[:8]:
            compact = compact_sources_for_node(conn, node.node_id, max_links=3)
            if compact:
                sources[node.node_id] = [ProvenanceSource(**item) for item in compact]

    decision_trail = []
    if should_include_history(
        include_history=request.include_history,
        intent=result.intent,
        query=request.query,
    ):
        decision_ids = [
            n.node_id
            for n in nodes
            if n.kind == "memory" and (n.subtype or "") in {"decision", "rule", "fact"}
        ][:3]
        decision_trail = build_decision_trail(conn, decision_ids)

    top_score = None
    if result.nodes:
        top_score = result.nodes[0].score
    confidence = score_confidence(
        abstained=result.abstained,
        top_score=top_score,
        result_count=len(nodes),
        min_bm25_strength=config.recall.min_bm25_strength,
    )

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
        sources=sources,
        confidence=confidence,
        decision_trail=decision_trail,
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
        extra_seed_ids=list(load_file_seeds(conn, request.session_id)),
        include_sources=request.include_sources,
    )
    hint = _maybe_queue_graph_sync(
        project_dir,
        config,
        existing_hint=result.graph_hint,
    )
    if hint != result.graph_hint:
        result = result.model_copy(update={"graph_hint": hint})

    # Confidence from pack density (neurons kept vs abstain-like emptiness).
    kept = len(result.truncation.included_ids)
    confidence = score_confidence(
        abstained=kept == 0,
        top_score=12.0 if kept >= 4 else (6.0 if kept >= 1 else None),
        result_count=kept,
        min_bm25_strength=config.recall.min_bm25_strength,
    )
    result = result.model_copy(update={"confidence": confidence})

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
    """Hook/CLI helper — not exposed as an MCP tool."""
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
    project_dir: Path | None = None,
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

    linked = linked_memories_for_code_nodes(
        conn,
        [n.node_id for n in nodes if n.kind == "code"],
    )
    # Keep linked memories inside remaining budget.
    linked = trim_neurons_to_budget(
        linked,
        budget=max(100, config.budget.total_tokens // 4),
    )

    hint = result.hint
    if project_dir is not None:
        hint = _maybe_queue_graph_sync(project_dir, config, existing_hint=hint)

    from brainkm.models.schemas import ImpactSummary

    impact = result.impact_summary
    if impact is not None and not isinstance(impact, ImpactSummary):
        impact = ImpactSummary.model_validate(impact)

    record_mcp_tool_use(conn, None, "traverse", result_count=len(nodes))
    _maintenance(conn)
    conn.commit()
    return TraverseResponse(
        from_ref=request.from_ref,
        resolved_id=result.resolved_id,
        nodes=nodes,
        hops_explored=result.hops_explored,
        hint=hint,
        impact_summary=impact,  # type: ignore[arg-type]
        linked_neurons=linked,
    )


def handle_forget(conn: sqlite3.Connection, request: ForgetRequest) -> ForgetResponse:
    """Service helper — MCP agents should use remember action=archive."""
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
    """Queue a sync request, or run extract+import synchronously when force=True.

    Kept for CLI/tests — not exposed as an MCP tool (auto-queued on stale reads).
    """
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
    return _graph_sync_response_from_result(result)


def _graph_sync_response_from_result(result) -> GraphSyncResponse:
    ok_statuses = {"completed", "ok", "skipped_empty"}
    status_ok = result.status in ok_statuses
    nodes = result.import_result.node_count if result.import_result else None
    edges = result.import_result.edge_count if result.import_result else None
    return GraphSyncResponse(
        requested=False,
        ran=True,
        ok=status_ok,
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

    if name == "traverse":
        request = TraverseRequest.model_validate(arguments)
        result = await _run_write(
            runtime,
            handle_traverse,
            request,
            config=config,
            project_dir=runtime.project_dir,
        )
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

    msg = f"unknown tool: {name}"
    raise ValueError(msg)
