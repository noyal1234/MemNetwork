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
    ContextPackRequest,
    ContextPackResponse,
    ForgetRequest,
    ForgetResponse,
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
from brainkm.services.config_loader import load_brain_config
from brainkm.services.context_pack import compile_context_pack
from brainkm.services.memory import forget_neuron, remember_neuron
from brainkm.services.recall import recall_live
from brainkm.services.recall_limit import get_recall_limit_state
from brainkm.services.remember_links import find_supersede_candidates, link_code_nodes_by_path
from brainkm.services.search import traverse
from brainkm.services.learning import get_learning_window
from brainkm.services.session_activity import get_session_activity
from brainkm.services.session_status import get_session_status, set_session_status


@dataclass(frozen=True)
class BrainRuntime:
    project_dir: Path

    @property
    def config(self) -> BrainConfig:
        return load_brain_config(self.project_dir)


def _ranked_to_neuron(conn: sqlite3.Connection, node_id: str, **scores: float) -> NeuronResult | None:
    row = conn.execute(
        """
        SELECT id, kind, subtype, title, content
        FROM nodes WHERE id = ? AND valid_until IS NULL
        """,
        (node_id,),
    ).fetchone()
    if row is None:
        return None
    return NeuronResult(
        node_id=row["id"],
        kind=row["kind"],
        subtype=row["subtype"],
        title=row["title"],
        content=row["content"],
        score=scores.get("score"),
        activation=scores.get("activation"),
    )


def handle_remember(conn: sqlite3.Connection, request: RememberRequest, *, config: BrainConfig) -> RememberResponse:
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
        neuron = _ranked_to_neuron(
            conn,
            ranked.node_id,
            score=ranked.score,
            activation=ranked.activation,
        )
        if neuron is not None:
            nodes.append(neuron)

    get_session_activity().track(request.session_id, [node.node_id for node in nodes])
    get_learning_window().record_neuron_hits(request.session_id, [node.node_id for node in nodes])

    return RecallResponse(
        query=result.query,
        nodes=nodes,
        abstained=result.abstained,
        source=result.source,
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
    get_learning_window().record_neuron_hits(
        request.session_id,
        [node.node_id for node in result.neurons],
    )
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
        neuron = _ranked_to_neuron(
            conn,
            ranked.node_id,
            score=ranked.score,
            activation=ranked.activation,
        )
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


def _write_op(runtime: BrainRuntime, fn, *args, **kwargs) -> Any:
    conn = connect(brain_db_path(runtime.project_dir))
    try:
        result = fn(conn, *args, **kwargs)
        return result
    finally:
        conn.close()


async def dispatch_tool(name: str, arguments: dict[str, Any], runtime: BrainRuntime) -> dict[str, Any]:
    """Route MCP tool call to the appropriate handler."""
    config = runtime.config

    if name == "remember":
        request = RememberRequest.model_validate(arguments)
        result = await _run_write(runtime, handle_remember, request, config=config)
        return result.model_dump()

    if name == "recall":
        request = RecallRequest.model_validate(arguments)
        result = _write_op(runtime, handle_recall, request, config=config, project_dir=runtime.project_dir)
        return result.model_dump()

    if name == "context_pack":
        request = ContextPackRequest.model_validate(arguments)
        result = _write_op(
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
        result = _write_op(runtime, handle_traverse, request, config=config)
        return result.model_dump()

    if name == "forget":
        request = ForgetRequest.model_validate(arguments)
        result = await _run_write(runtime, handle_forget, request)
        return result.model_dump()

    msg = f"unknown tool: {name}"
    raise ValueError(msg)


async def _run_write(runtime: BrainRuntime, fn, *args, **kwargs) -> Any:
    from brainkm.services.write_queue import get_write_queue

    queue = get_write_queue()
    return await queue.run(_write_op, runtime, fn, *args, **kwargs)
