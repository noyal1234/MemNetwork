"""Pydantic models for MCP tool I/O."""

from __future__ import annotations

from typing import Any, Literal

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
    """Pin durable project truth, correct a wrong capture, or archive a neuron."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(
        default=None,
        min_length=1,
        description="Neuron body text (aliases accepted at parse time: content, text)",
    )
    kind: Literal["memory"] = Field(
        default="memory",
        description="MCP remember only creates durable memory neurons",
    )
    subtype: Literal["fact", "decision", "pattern", "context", "rule", "error"] = Field(
        default="fact",
        description="Durable memory subtype (fact|decision|pattern|context|rule|error)",
    )
    tags: list[str] = Field(default_factory=list)
    session_id: str | None = None
    action: Literal["pin", "correct", "archive"] = Field(
        default="pin",
        description=(
            "pin=store durable truth; correct=write replacement and supersede "
            "target_node_id; archive=soft-delete target_node_id (absorbs forget)"
        ),
    )
    target_node_id: str | None = Field(
        default=None,
        description="Required for archive; required for correct (node being replaced)",
    )
    reason: str | None = Field(
        default=None,
        description="Optional archive/correct reason for audit_log",
    )

    @model_validator(mode="before")
    @classmethod
    def map_remember_aliases(cls, data: Any) -> Any:
        """Accept common LLM aliases (content/text → body; name/summary → title)."""
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if not out.get("body"):
            for key in ("content", "text"):
                value = out.get(key)
                if isinstance(value, str) and value.strip():
                    out["body"] = value
                    break
        if not out.get("title"):
            for key in ("name", "summary"):
                value = out.get(key)
                if isinstance(value, str) and value.strip():
                    out["title"] = value.strip()[:200]
                    break
        # Last resort for pin/correct: derive a short title from the body.
        action = str(out.get("action") or "pin").strip().lower()
        if action != "archive" and not out.get("title"):
            body = out.get("body")
            if isinstance(body, str) and body.strip():
                first = body.strip().splitlines()[0].strip()
                out["title"] = first[:60] if first else None
        return out

    @model_validator(mode="after")
    def validate_action_fields(self) -> RememberRequest:
        if self.action == "archive":
            if not self.target_node_id:
                msg = "remember action=archive requires target_node_id"
                raise ValueError(msg)
            return self
        if not self.title or not self.body:
            msg = "remember action=pin|correct requires title and body"
            raise ValueError(msg)
        if self.action == "correct" and not self.target_node_id:
            msg = "remember action=correct requires target_node_id"
            raise ValueError(msg)
        return self


class RememberResponse(BaseModel):
    node_id: str | None = None
    title: str | None = None
    linked_code_nodes: list[str] = Field(default_factory=list)
    supersede_candidates: list[str] = Field(default_factory=list)
    conflict_suggestions: list[str] = Field(
        default_factory=list,
        description="Near-duplicate nodes with a conflicting claim — prefer supersede",
    )
    archived_node_id: str | None = None
    superseded_node_id: str | None = None
    action: Literal["pin", "correct", "archive"] = "pin"


class DecisionTrailEntry(BaseModel):
    node_id: str
    title: str
    subtype: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    superseded_by: str | None = None


class RecallRequest(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(default=5, ge=1, le=20)
    session_id: str | None = None
    truncation_followup: bool = Field(
        default=False,
        description="Exempt from max_recalls_per_turn when fetching omitted neurons",
    )
    include_sources: bool | None = Field(
        default=None,
        description="Attach compact provenance; defaults to BrainConfig.recall.include_sources",
    )
    include_history: bool | None = Field(
        default=None,
        description=(
            "Follow supersedes chains for decision neurons. "
            "Default: auto for why/history/decision intents."
        ),
    )


class ProvenanceSource(BaseModel):
    session_id: str | None = None
    id: str
    via: str


class RecallResponse(BaseModel):
    query: str
    nodes: list[NeuronResult]
    abstained: bool = False
    source: str = "live_db"
    session_chunks: list[SessionChunkResult] = Field(default_factory=list)
    intent: str | None = None
    sources: dict[str, list[ProvenanceSource]] = Field(
        default_factory=dict,
        description="Optional provenance keyed by node_id when include_sources is on",
    )
    confidence: Literal["high", "medium", "low"] = "medium"
    decision_trail: list[DecisionTrailEntry] = Field(
        default_factory=list,
        description="Ordered supersede history for top decision hits (newest first)",
    )


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
    include_sources: bool | None = Field(
        default=None,
        description="Attach compact provenance; defaults to BrainConfig.recall.include_sources",
    )


class TruncationManifest(BaseModel):
    included_ids: list[str] = Field(default_factory=list)
    omitted_ids: list[str] = Field(default_factory=list)
    token_budget: int = 0
    tokens_used: int = 0


class ContextPackResponse(BaseModel):
    query: str
    pack_text: str = Field(
        description=(
            "Formatted pack (decisions + code neighborhood). Primary agent-facing "
            "payload — prefer this over neurons/graph_nodes when include_structured "
            "was false (default)."
        ),
    )
    neurons: list[NeuronResult] = Field(
        default_factory=list,
        description=(
            "Structured memory hits. Empty by default to save tokens; set "
            "include_structured=true to duplicate pack_text into this array."
        ),
    )
    graph_nodes: list[NeuronResult] = Field(
        default_factory=list,
        description=(
            "Structured code-graph neighborhood. Empty by default; set "
            "include_structured=true to populate (duplicates pack_text)."
        ),
    )
    truncation: TruncationManifest
    graph_available: bool = True
    graph_hint: str | None = None
    sources: dict[str, list[ProvenanceSource]] = Field(default_factory=dict)
    confidence: Literal["high", "medium", "low"] = "medium"


class SessionStatusRequest(BaseModel):
    """CLI/hook I/O — no longer an MCP tool."""

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
        min_length=1,
        description=(
            "Symbol name, file path, or node ID to traverse from. "
            "For blast-radius: what calls/imports this symbol? "
            "Aliases accepted at parse time: query, symbol, path."
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
    session_id: str | None = Field(
        default=None,
        description="Optional session id for per-session MCP telemetry (brain_stats)",
    )

    @model_validator(mode="before")
    @classmethod
    def map_traverse_aliases(cls, data: Any) -> Any:
        """Accept common LLM aliases (query/symbol/path → from_ref)."""
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if not out.get("from_ref"):
            for key in ("query", "symbol", "path"):
                value = out.get(key)
                if isinstance(value, str) and value.strip():
                    out["from_ref"] = value.strip()
                    break
        return out


class ImpactSummary(BaseModel):
    neighbor_count: int = 0
    by_hop: dict[str, int] = Field(
        default_factory=dict,
        description='Neighbor counts keyed by hop depth as string ("1", "2")',
    )
    high_fan_in: list[dict[str, object]] = Field(
        default_factory=list,
        description="Neighbors with high inbound call/import degree (change risk)",
    )
    risk_flag: bool = False


class TraverseResponse(BaseModel):
    from_ref: str
    resolved_id: str | None = None
    nodes: list[NeuronResult]
    hops_explored: int = 0
    hint: str | None = None
    impact_summary: ImpactSummary | None = None
    linked_neurons: list[NeuronResult] = Field(
        default_factory=list,
        description="Decision/error memories linked to impacted code nodes (via=code id)",
    )
    candidates: list[dict[str, str]] = Field(
        default_factory=list,
        description="Up to 3 alternate node id/label hints when from_ref is ambiguous",
    )
    abstain_reason: Literal["unresolved", "ambiguous"] | None = Field(
        default=None,
        description="When abstained: unresolved (no match) vs ambiguous (multiple)",
    )


class ForgetRequest(BaseModel):
    """Service/CLI I/O — absorbed into remember action=archive for MCP."""

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
        description=(
            "Active memory-kind neurons with use_count=0 and no pending "
            "neuron_hit rows — hygiene signal only, not total pack/content "
            "delivery (code-graph / procedure-only packs do not clear this)"
        ),
    )
    hygiene_hint: str | None = Field(
        default=None,
        description="Suggested hygiene action when dead/noisy neurons accumulate",
    )
    outbound_gate_7d: dict[str, int] = Field(
        default_factory=dict,
        description="Outbound injection-gate fires in 7d keyed by block|strip|noise",
    )
    traverse_abstain_7d: dict[str, int] = Field(
        default_factory=dict,
        description="Traverse abstentions in 7d keyed by unresolved|ambiguous",
    )
    compression: dict[str, object] = Field(
        default_factory=dict,
        description=(
            "Compression rollups (tokens_in/out by surface), engine_version, "
            "cache_ttl_seconds — the configured dual-store cache expiry, "
            "enforced by dual_store.get_compressed_view"
        ),
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
    """CLI I/O — graph sync is automatic from MCP read tools when stale."""

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


class TraceChangesRequest(BaseModel):
    path: str = Field(
        ...,
        min_length=1,
        description=(
            "Single project-relative source file/directory path to trace "
            "(no globs or git pathspec magic)"
        ),
    )
    session_id: str | None = Field(
        default=None,
        description="Optional session id for uncommitted file_seed attribution",
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=40,
        description="Max commits from live git log",
    )


class TraceLinkedNeuron(BaseModel):
    node_id: str
    kind: str
    subtype: str | None = None
    title: str


class TraceCommitEntry(BaseModel):
    git_hash: str
    subject: str
    author_date: str | None = None
    commit_node_id: str | None = None
    session_id: str | None = None
    linked_neurons: list[TraceLinkedNeuron] = Field(default_factory=list)


class TraceUncommitted(BaseModel):
    dirty: bool = False
    diff_stat: str | None = None
    agent_touched: bool = False
    session_ids: list[str] = Field(default_factory=list)


class TraceChangesResponse(BaseModel):
    path: str
    pack_text: str
    commits: list[TraceCommitEntry] = Field(default_factory=list)
    uncommitted: TraceUncommitted = Field(default_factory=TraceUncommitted)
    truncation: TruncationManifest
    hint: str | None = None


class FeedbackRequest(BaseModel):
    """Explicit signal on a node_id previously returned by recall/context_pack/traverse."""

    node_ids: list[str] = Field(..., min_length=1, max_length=20)
    signal: Literal["used", "not_used", "wrong"] = Field(
        ...,
        description=(
            "used=this was the answer; wrong=this was incorrect/misleading; "
            "not_used=looked at it, not relevant (neutral, no-op)"
        ),
    )
    session_id: str | None = None


class FeedbackResponse(BaseModel):
    updated: list[str] = Field(default_factory=list)


class CheckpointRequest(BaseModel):
    """Force a handover distill outside host PreCompact (Antigravity, generic MCP)."""

    session_id: str | None = None
    reason: str | None = Field(
        default=None,
        description="Optional note for why checkpoint was called (audit only)",
    )


class CheckpointResponse(BaseModel):
    checkpoint_ok: bool = False
    neuron_count: int = 0
    skipped: bool = False
    reason: str | None = None
