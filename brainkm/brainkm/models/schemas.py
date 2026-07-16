"""Pydantic models for MCP tool I/O."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class NeuronResult(BaseModel):
    node_id: str
    kind: str
    subtype: str | None = None
    title: str
    content: str | None = None
    score: float | None = None
    activation: float | None = None
    path: str | None = None
    relationship: str | None = None
    via: str | None = None


class SessionChunkResult(BaseModel):
    chunk_id: str
    excerpt: str
    score: float | None = None


class RememberRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1)
    kind: str = Field(default="memory")
    subtype: str = Field(default="fact")
    tags: list[str] = Field(default_factory=list)
    session_id: str | None = None


class RememberResponse(BaseModel):
    node_id: str
    title: str
    linked_code_nodes: list[str] = Field(default_factory=list)
    supersede_candidates: list[str] = Field(default_factory=list)
    conflict_suggestions: list[str] = Field(
        default_factory=list,
        description="Near-duplicate nodes with a conflicting claim — prefer supersede",
    )


class RecallRequest(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(default=5, ge=1, le=20)
    session_id: str | None = None
    truncation_followup: bool = Field(
        default=False,
        description="Exempt from max_recalls_per_turn when fetching omitted neurons",
    )


class RecallResponse(BaseModel):
    query: str
    nodes: list[NeuronResult]
    abstained: bool = False
    source: str = "live_db"
    session_chunks: list[SessionChunkResult] = Field(default_factory=list)
    intent: str | None = None


class ContextPackRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        description=(
            "Task query. Include a symbol name or file path so the code neighborhood "
            "can be seeded (or pass seed_refs). For pure call/import questions use traverse."
        ),
    )
    session_id: str | None = None
    seed_refs: list[str] = Field(
        default_factory=list,
        description="Optional symbol names or file paths to seed the code-graph neighborhood",
        max_length=5,
    )
    include_structured: bool = Field(
        default=False,
        description=(
            "When true, include full neurons/graph_nodes arrays (duplicates pack_text). "
            "Default false to keep MCP payload within the token budget."
        ),
    )
    summary_first: bool | None = Field(
        default=None,
        description=(
            "When true, pack_text uses titles + one-line gists; expand via recall "
            "truncation_followup. Defaults to BrainConfig.compression.summary_first."
        ),
    )


class TruncationManifest(BaseModel):
    included_ids: list[str] = Field(default_factory=list)
    omitted_ids: list[str] = Field(default_factory=list)
    token_budget: int = 0
    tokens_used: int = 0


class ContextPackResponse(BaseModel):
    query: str
    pack_text: str
    neurons: list[NeuronResult]
    graph_nodes: list[NeuronResult] = Field(default_factory=list)
    truncation: TruncationManifest
    graph_available: bool = True
    graph_hint: str | None = None


class SessionStatusRequest(BaseModel):
    session_id: str | None = None
    title: str | None = None
    body: str | None = None

    @model_validator(mode="after")
    def title_and_body_together(self) -> SessionStatusRequest:
        if (self.title is None) ^ (self.body is None):
            msg = "session_status requires both title and body together, or neither (read)"
            raise ValueError(msg)
        return self


class SessionStatusResponse(BaseModel):
    node_id: str | None = None
    title: str | None = None
    body: str | None = None
    updated: bool = False


class TraverseRequest(BaseModel):
    from_ref: str = Field(
        ...,
        description=(
            "Symbol name, file path, or node ID to traverse from. "
            "For blast-radius: what calls/imports this symbol?"
        ),
    )
    to_ref: str | None = Field(
        None,
        description="Optional target symbol/path; omit for neighborhood around from_ref",
    )
    max_hops: int = Field(default=1, ge=1, le=2)
    relationship: str | None = Field(
        None,
        description=(
            "Edge filter. Default (omit): structural flow edges "
            "(calls, imports, imports_from, defines, contains, method, uses, inherits). "
            "Pass a type, comma-list, or '*' for all edges including references."
        ),
    )
    direction: Literal["out", "in", "both"] = Field(
        default="both",
        description=(
            "Edge direction. both (default)=callers+callees; "
            "in=callers/importers of from_ref; out=callees/exports from from_ref."
        ),
    )


class TraverseResponse(BaseModel):
    from_ref: str
    resolved_id: str | None = None
    nodes: list[NeuronResult]
    hops_explored: int = 0
    hint: str | None = None


class ForgetRequest(BaseModel):
    node_id: str = Field(..., min_length=1)
    reason: str | None = None


class ForgetResponse(BaseModel):
    node_id: str
    archived: bool
    valid_until: str | None = None


class BrainStatsRequest(BaseModel):
    session_id: str | None = None


class BrainStatsResponse(BaseModel):
    neurons_by_kind: dict[str, int] = Field(default_factory=dict)
    neurons_by_subtype: dict[str, int] = Field(default_factory=dict)
    graph_nodes: int = 0
    graph_edges: int = 0
    graph_available: bool = False
    last_graph_import_at: str | None = None
    graph_stale: bool | None = None
    review_queue_size: int = 0
    abstention_mode: str | None = None
    abstention_calibrated: bool = False
    mcp_calls_by_tool: dict[str, int] = Field(
        default_factory=dict,
        description="MCP tool invocation counts in the last 7 days",
    )
    mcp_calls_30d: int = 0
    abstention_rate_7d: float | None = Field(
        default=None,
        description="Fraction of MCP recalls that abstained in the last 7 days",
    )
    dead_neuron_count: int = Field(
        default=0,
        description="Active memory neurons with use_count=0 and no pending hits",
    )
    # Optional session-scoped fields (populated when request.session_id is set)
    session_id: str | None = None
    session_mcp_calls_by_tool: dict[str, int] = Field(
        default_factory=dict,
        description="MCP tool counts for the requested session_id",
    )
    session_neuron_hits: int = Field(
        default=0,
        description="Neuron hit events recorded for the requested session",
    )
    session_injection_tokens: int | None = Field(
        default=None,
        description="Frozen SessionStart pack token_count for the session, if any",
    )
    session_distill_mode: str | None = Field(
        default=None,
        description="Distill mode recorded in ingested_sessions for the session",
    )
    session_neuron_count: int | None = Field(
        default=None,
        description="Neurons distilled for the session (ingested_sessions.neuron_count)",
    )


class GraphSyncRequest(BaseModel):
    force: bool = Field(
        default=False,
        description="Run extract+import immediately instead of only queuing a request flag",
    )
    skip_extract: bool = Field(
        default=False,
        description="Import existing graph.json only (force mode)",
    )


class GraphSyncResponse(BaseModel):
    requested: bool = False
    ran: bool = False
    ok: bool = False
    message: str | None = None
    nodes_imported: int | None = None
    edges_imported: int | None = None
