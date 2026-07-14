"""MCP tool dispatch — thin handlers delegating to services."""

from __future__ import annotations

import asyncio
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
    SessionChunkResult,
    SessionStatusRequest,
    SessionStatusResponse,
    TraverseRequest,
    TraverseResponse,
)
from brainkm.services.brain_stats import collect_brain_stats
from brainkm.services.config_loader import load_brain_config
from brainkm.services.context_pack import compile_context_pack
from brainkm.services.learning import persist_neuron_hits
from brainkm.services.memory import forget_neuron, remember_neuron
from brainkm.services.recall import recall_live
from brainkm.services.recall_limit import get_recall_limit_state
from brainkm.services.remember_links import find_supersede_candidates, link_code_nodes_by_path
from brainkm.services.search import RankedNode, traverse
from brainkm.services.session_status import get_session_status, set_session_status


@dataclass(frozen=True)
class BrainRuntime:
    project_dir: Path

    @property
    def config(self) -> BrainConfig:
        return load_brain_config(self.project_dir)


def _ranked_to_neuron(conn: sqlite3.Connection, ranked: RankedNode) -> NeuronResult | None:
    row = conn.execute(
        """
        SELECT id, kind, subtype, title, content, path
        FROM nodes WHERE id = ? AND valid_until IS NULL
        """,
        (ranked.node_id,),
    ).fetchone()
    if row is None:
        return None
    return NeuronResult(
        node_id=row["id"],
        kind=row["kind"],
        subtype=row["subtype"],
        title=row["title"],
        content=row["content"],
        score=ranked.score,
        activation=ranked.activation,
        path=row["path"] or ranked.path,
        relationship=ranked.relationship,
        via=ranked.via,
    )


def handle_remember(conn: sqlite3.Connection, request: RememberRequest) -> RememberResponse:
    record = remember_neuron(
        conn,
        title=request.title,
        content=request.body,
        kind=request.kind,
        subtype=request.subtype,
        tags=request.tags,
        session_id=request.session_id,
        source="mcp_remember",
    )
    linked = link_code_nodes_by_path(
        conn,
        record.id,
        title=record.title,
        content=record.content or "",
    )
    candidates = find_supersede_candidates(
        conn,
        title=record.title,
        content=record.content or "",
        exclude_id=record.id,
    )
    conn.commit()
    return RememberResponse(
        node_id=record.id,
        title=record.title,
        linked_code_nodes=linked,
        supersede_candidates=candidates,
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
        return RecallResponse(query=request.query, nodes=[], abstained=True, source="rate_limited")

    effective_limit = request.limit
    result = recall_live(
        conn,
        request.query,
        limit=effective_limit,
        graph=config.graph,
        recall=config.recall,
        project_dir=project_dir,
    )
    nodes: list[NeuronResult] = []
    for ranked in result.nodes:
        neuron = _ranked_to_neuron(conn, ranked)
        if neuron is not None:
            nodes.append(neuron)

    hit_ids = [node.node_id for node in nodes]
    persist_neuron_hits(
        conn,
        request.session_id,
        hit_ids,
        source="recall",
        cap=config.learning.session_window_size,
    )
    conn.commit()

    chunks = [
        SessionChunkResult(
            chunk_id=chunk.chunk_id,
            excerpt=(chunk.content[:240] + "…") if len(chunk.content) > 240 else chunk.content,
            score=chunk.score,
        )
        for chunk in result.session_chunks
    ]

    return RecallResponse(
        query=result.query,
        nodes=nodes,
        abstained=result.abstained,
        source=result.source,
        session_chunks=chunks,
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
    )
    persist_neuron_hits(
        conn,
        request.session_id,
        [node.node_id for node in result.neurons],
        source="context_pack",
        cap=config.learning.session_window_size,
    )
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
        conn.commit()
        return SessionStatusResponse(
            node_id=record.id,
            title=record.title,
            body=record.content,
            updated=True,
        )

    record = get_session_status(conn, session_id=request.session_id)
    if record is None:
        return SessionStatusResponse()
    return SessionStatusResponse(
        node_id=record.id,
        title=record.title,
        body=record.content,
        updated=False,
    )


def handle_traverse(conn: sqlite3.Connection, request: TraverseRequest, *, config: BrainConfig) -> TraverseResponse:
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
        neuron = _ranked_to_neuron(conn, ranked)
        if neuron is not None:
            nodes.append(neuron)
    return TraverseResponse(
        from_ref=request.from_ref,
        nodes=nodes,
        hops_explored=result.hops_explored,
    )


def handle_forget(conn: sqlite3.Connection, request: ForgetRequest) -> ForgetResponse:
    archived = forget_neuron(conn, request.node_id, reason=request.reason)
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
    _ = request  # reserved for future session-scoped stats
    return collect_brain_stats(conn, config=config, project_dir=project_dir)


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


async def _run_read(runtime: BrainRuntime, fn, *args, **kwargs) -> Any:
    """Run sync SQLite read/compute work off the asyncio event loop."""
    return await asyncio.to_thread(_write_op, runtime, fn, *args, **kwargs)


async def dispatch_tool(name: str, arguments: dict[str, Any], runtime: BrainRuntime) -> dict[str, Any]:
    """Route MCP tool call to the appropriate handler."""
    config = runtime.config

    if name == "remember":
        request = RememberRequest.model_validate(arguments)
        result = await _run_write(runtime, handle_remember, request)
        return result.model_dump()

    if name == "recall":
        request = RecallRequest.model_validate(arguments)
        result = await _run_read(
            runtime,
            handle_recall,
            request,
            config=config,
            project_dir=runtime.project_dir,
        )
        return result.model_dump()

    if name == "context_pack":
        request = ContextPackRequest.model_validate(arguments)
        result = await _run_read(
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
        result = await _run_read(runtime, handle_traverse, request, config=config)
        return result.model_dump()

    if name == "forget":
        request = ForgetRequest.model_validate(arguments)
        result = await _run_write(runtime, handle_forget, request)
        return result.model_dump()

    if name == "brain_stats":
        request = BrainStatsRequest.model_validate(arguments or {})
        result = await _run_read(
            runtime,
            handle_brain_stats,
            request,
            config=config,
            project_dir=runtime.project_dir,
        )
        return result.model_dump()

    if name == "graph_sync":
        request = GraphSyncRequest.model_validate(arguments or {})
        result = await asyncio.to_thread(
            handle_graph_sync,
            runtime.project_dir,
            request,
            config=config,
        )
        return result.model_dump()

    msg = f"unknown tool: {name}"
    raise ValueError(msg)


async def _run_write(runtime: BrainRuntime, fn, *args, **kwargs) -> Any:
    from brainkm.services.write_queue import get_write_queue

    queue = get_write_queue()
    return await queue.run(_write_op, runtime, fn, *args, **kwargs)
