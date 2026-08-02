"""Pydantic schema for per-project `.brain/config.json`."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class SessionStartBudget(BaseModel):
    pinned_rules: int = Field(default=300, ge=0)
    session_status: int = Field(default=150, ge=0)
    procedure_stubs: int = Field(default=60, ge=0)
    recall_top: int = Field(default=200, ge=0)


class PreToolBudget(BaseModel):
    procedure_expanded: int = Field(default=250, ge=0)
    graph_neighborhood: int = Field(default=400, ge=0)


class PackQuotasConfig(BaseModel):
    """Default channel shares for context_pack (~40/40/20 when quotas enabled)."""

    enabled: bool = True
    neurons_fraction: float = Field(default=0.40, ge=0.1, le=0.8)
    graph_fraction: float = Field(default=0.40, ge=0.1, le=0.8)
    procedures_fraction: float = Field(default=0.20, ge=0.05, le=0.5)


class BudgetConfig(BaseModel):
    total_tokens: int = Field(default=1500, ge=100, le=8000)
    dynamic_reallocation: bool = True
    session_start: SessionStartBudget = Field(default_factory=SessionStartBudget)
    pre_tool: PreToolBudget = Field(default_factory=PreToolBudget)
    pack_quotas: PackQuotasConfig = Field(default_factory=PackQuotasConfig)


class CaptureConfig(BaseModel):
    transcripts: bool = True
    plan_files: bool = True
    plan_glob: str = ".cursor/plans/*.plan.md"
    distill_mode: Literal[
        "cursor", "claude", "antigravity", "codex", "ollama", "groq", "rules", "mcp"
    ] = "cursor"
    max_auto_neurons_per_session: int = Field(default=50, ge=1, le=500)
    max_neurons_per_plan: int = Field(default=20, ge=1, le=200)
    auto_hygiene: bool = True
    # Passive hook observations (default off for stdio/CI; http install enables).
    auto_observe: bool = False
    observe_max_per_session: int = Field(default=40, ge=1, le=200)
    observe_dedup_window_seconds: int = Field(default=300, ge=30, le=3600)
    observe_max_body_tokens: int = Field(default=80, ge=20, le=200)
    observation_ttl_hours: int = Field(
        default=72,
        ge=0,
        le=8760,
        description="Soft-archive unpromoted observations older than this (0=disable)",
    )
    cloud_distill_acknowledged: bool = Field(
        default=False,
        description=(
            "User consent that transcript content may leave the machine when "
            "distill_mode is groq (required before cloud upload)"
        ),
    )
    auto_supersede_conflicts: bool = Field(
        default=False,
        description=(
            "When true, remember action=pin auto-supersedes the top high-confidence "
            "conflict suggestion (still prefer explicit action=correct)"
        ),
    )
    detect_tool_failure: bool = Field(
        default=True,
        description=(
            "Infer tool failure from the PostToolUse payload (is_error/exit_code/"
            "error text fields). Only Claude has a native PostToolUseFailure event "
            "(Cursor does not — see install.CURSOR_UNSUPPORTED_HOOK_EVENTS); this "
            "makes tool_feedback and FAIL observations host-neutral. Conservative "
            "matcher — set false if it produces false-positive error neurons."
        ),
    )

    @field_validator("distill_mode", mode="before")
    @classmethod
    def _coerce_legacy_mcp_distill(cls, value: object) -> object:
        if isinstance(value, str) and value.strip().lower() == "mcp":
            return "claude"
        return value


class InjectionConfig(BaseModel):
    session_start: bool = True
    # Shell/Bash packs only when derive_pre_tool_query finds a path/symbol seed
    # (plain grep/wc never inject). run_terminal aliases Shell|Bash|run_terminal_cmd.
    pre_tool_patterns: list[str] = Field(
        default_factory=lambda: ["write", "edit", "run_terminal"]
    )
    # Despite the name, this is not enforced per conversational turn — hooks
    # run in separate subprocesses from the long-lived MCP server and cannot
    # reset its in-process RecallLimitState, so there is no real turn boundary
    # to push in. It is a rolling RecallLimitState.window_seconds (30s) cap
    # instead: N recalls within any 30s window, not N per user message.
    max_recalls_per_turn: int = Field(default=3, ge=0, le=5)
    frozen_snapshot: bool = True
    routing_nudge: bool = True
    routing_nudge_max_per_session: int = Field(default=5, ge=0)
    # PreToolUse tools that only get a routing nudge (not a context_pack).
    routing_nudge_pretool_patterns: list[str] = Field(
        default_factory=lambda: ["read", "grep", "glob"]
    )
    # After a real MCP call, re-arm nudge once this many tool_use rows follow.
    routing_nudge_rearm_after_calls: int = Field(default=12, ge=1)
    # Deny (not just nudge) shell commands that exactly duplicate a brainkm
    # tool — currently single-file `git log/blame` vs trace_changes. Advisory
    # context loses to habit; only a deny reliably re-routes. Claude Code only.
    deny_redundant_shell: bool = True


class LearningConfig(BaseModel):
    co_activation_threshold: int = Field(default=3, ge=1)
    max_tool_nodes: int = Field(default=20, ge=1, le=50)
    auto_capture_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    session_window_size: int = Field(default=20, ge=5, le=100)
    co_activation_delta: float = Field(default=1.0, gt=0.0)
    co_activation_max_weight: float = Field(default=10.0, ge=1.0)
    co_activation_idle_days: int = Field(default=30, ge=1)
    co_activation_decay_factor: float = Field(default=0.5, gt=0.0, le=1.0)
    co_activation_min_weight: float = Field(default=0.3, ge=0.0)
    promote_max_ignore_rate: float = Field(default=0.5, ge=0.0, le=1.0)
    promote_min_injected_count: int = Field(default=3, ge=1)
    archive_min_injected_count: int = Field(default=5, ge=1)
    promote_ignore_half_life_days: int = Field(default=60, ge=1)
    session_state_retention_days: int = Field(default=14, ge=1)

    @model_validator(mode="after")
    def _validate_learning_bounds(self) -> LearningConfig:
        if self.co_activation_max_weight < float(self.co_activation_threshold):
            raise ValueError(
                "co_activation_max_weight must be >= co_activation_threshold"
            )
        if self.archive_min_injected_count < self.promote_min_injected_count:
            raise ValueError(
                "archive_min_injected_count must be >= promote_min_injected_count"
            )
        return self


class RecallConfig(BaseModel):
    abstain_on_low_confidence: bool = True
    abstain_mode: Literal["percentile", "absolute"] = "percentile"
    abstain_percentile: float = Field(default=0.10, ge=0.0, le=1.0)
    min_recall_score: float | None = Field(default=None, ge=0.0, le=100.0)
    min_bm25_strength: float | None = Field(
        default=3.0,
        ge=0.0,
        description="Percentile mode: abstain when |best BM25| is below this (weak single-token hits)",  # noqa: E501
    )
    activation: Literal["bfs", "ppr"] = "ppr"
    ppr_damping: float = Field(default=0.85, ge=0.5, le=0.99)
    ppr_iterations: int = Field(default=8, ge=2, le=30)
    rerank: bool = False
    decay_half_life_days: float = Field(default=30.0, ge=1.0, le=3650.0)
    feedback_boost: bool = True
    direct_match_boost: float = Field(
        default=1.6,
        ge=1.0,
        le=5.0,
        description=(
            "Recall-only multiplier for nodes that matched the query text directly (FTS), "
            "so PPR hubs reached via co_activated edges cannot outrank literal matches. "
            "1.0 disables."
        ),
    )
    max_per_session: int = Field(
        default=3,
        ge=1,
        le=20,
        description="Cap recall/pack hits sharing the same session_id",
    )
    max_per_kind: dict[str, int] = Field(
        default_factory=lambda: {
            "memory": 8,
            "code": 12,
            "procedure": 3,
            "concept": 0,
        },
        description="Cap hits per node kind after score sort (0 = never surface)",
    )
    include_sources: bool = Field(
        default=False,
        description="Attach compact provenance sources on recall/context_pack",
    )
    expand_relationships: list[str] = Field(
        default_factory=lambda: [
            "about_file",
            "about_symbol",
            "mentions_concept",
            "implements_concept",
            "supersedes",
            "calls",
            "imports",
            "imports_from",
            "defines",
            "contains",
            "method",
            "uses",
            "inherits",
            "co_activated",
            "spawned",
            "distilled_from",
            "relates_to",
        ],
        description="Allowlisted edge types for PPR/BFS expand",
    )

    @model_validator(mode="after")
    def absolute_mode_requires_threshold(self) -> RecallConfig:
        if self.abstain_mode == "absolute" and self.min_recall_score is None:
            msg = "min_recall_score is required when abstain_mode is 'absolute'"
            raise ValueError(msg)
        # Concept tags are indexing glue — never surface in agent packs
        # (even when older config.json still lists concept: 4).
        kinds = dict(self.max_per_kind)
        kinds["concept"] = 0
        self.max_per_kind = kinds
        return self


class SemanticConfig(BaseModel):
    """T1 hybrid retrieval (vector + BM25). Off by default for zero-dep T0."""

    enabled: bool = False
    prefer_onnx: bool = True
    vector_limit: int = Field(default=20, ge=5, le=100)
    rrf_k: int = Field(default=60, ge=10, le=200)
    embed_on_write: bool = True
    fusion_mode: Literal["rrf", "fts_primary"] = Field(
        default="rrf",
        description=(
            "rrf = classic Reciprocal Rank Fusion; "
            "fts_primary = keep FTS candidate set, re-rank by vector (safer on long haystacks)"
        ),
    )


class DecayConfig(BaseModel):
    enabled: bool = True
    unused_days: int = Field(default=90, ge=7, le=3650)
    consolidate_on_session_end: bool = False


class CompressionConfig(BaseModel):
    write_time: bool = True
    max_body_tokens: int = Field(default=120, ge=40, le=800)
    pack_dedup: bool = True
    pack_diversity: bool = True
    summary_first: bool = True
    # Content-class pipeline (default ON — core usecase)
    pipeline_enabled: bool = True
    rtk_lite_enabled: bool = True
    prose_intensity: Literal["off", "lite", "full"] = "lite"
    inflation_guard: bool = True
    session_dedup: bool = True
    # Dual-store / canary
    engine_version: str = "1"
    engine_version_override: str | None = None
    canary_engine_version: str | None = None
    canary_pct: float = Field(default=0.0, ge=0.0, le=1.0)
    canary_salt: str = "brainkm-compression"
    # Decision egress: lossy prose only when polarity rubric would pass (runtime check)
    decision_egress_lossy: bool = False
    decision_egress_min_pct: float = Field(default=95.0, ge=50.0, le=100.0)
    # Optional ML (fail-open; never default)
    llmlingua_enabled: bool = False
    llmlingua_min_tokens: int = Field(default=400, ge=100, le=8000)
    llmlingua_rate: float = Field(default=0.5, ge=0.1, le=0.9)
    # Cache / cost modeling
    cache_ttl_seconds: float = Field(default=300.0, ge=60.0, le=86400.0)


class HandoverConfig(BaseModel):
    precompact_enabled: bool = True
    precompact_distill_timeout_seconds: int = Field(default=30, ge=1, le=120)
    export_markdown: bool = True


class GraphConfig(BaseModel):
    max_bfs_fanout_per_hop: int = Field(default=50, ge=1, le=200)
    max_activation_nodes: int = Field(default=500, ge=10, le=5000)
    min_edge_weight_to_traverse: float = Field(default=0.3, ge=0.0, le=1.0)


class GraphifyAutoSyncConfig(BaseModel):
    enabled: bool = True
    debounce_seconds: float = Field(default=60.0, ge=1.0, le=600.0)
    min_interval_seconds: float = Field(default=300.0, ge=10.0, le=3600.0)
    trigger_on_post_tool: bool = True
    watch_filesystem: bool = False


class GraphifyConfig(BaseModel):
    enabled: bool = True
    output_dir: str = "graphify-out"
    graph_json: str = "graphify-out/graph.json"
    code_only: bool = True
    extract_binary: str = "graphify"
    extract_extra_args: list[str] = Field(default_factory=list)
    extract_scope: Literal["project", "project_roots"] = "project_roots"
    extract_timeout_seconds: int = Field(default=300, ge=30, le=1800)
    sync_on_install: bool = True
    auto_sync: GraphifyAutoSyncConfig = Field(default_factory=GraphifyAutoSyncConfig)


class OllamaConfig(BaseModel):
    base_url: str = "http://127.0.0.1:11434"
    model: str = "qwen2.5:3b"
    auto_select_model: bool = False
    timeout_seconds: int = Field(default=120, ge=5, le=600)


class GroqConfig(BaseModel):
    base_url: str = "https://api.groq.com/openai/v1"
    model: str = "llama-3.3-70b-versatile"
    timeout_seconds: int = Field(default=60, ge=5, le=300)


class GitConfig(BaseModel):
    enabled: bool = False
    link_on_capture: bool = True
    commit_trace: bool = Field(
        default=True,
        description=(
            "Install a post-commit hook that runs `brainkm git-note` to store "
            "sha→session→neuron joins (diffs stay in git, queried live by trace)."
        ),
    )
    commit_retention_days: int = Field(
        default=90,
        ge=7,
        le=3650,
        description=(
            "Hygiene soft-archives kind=commit nodes older than this many days "
            "when they have no relates_to edges to active memories."
        ),
    )


class TeamConfig(BaseModel):
    """Git-shareable curated team neurons under ``.brain/team/``."""

    auto_import_on_install: bool = True
    team_dir: str = "team"


class McpConfig(BaseModel):
    """How clients reach the brainkm MCP server."""

    transport: Literal["stdio", "http"] = "stdio"
    http_host: str = "127.0.0.1"
    http_port: int = Field(default=8765, ge=1, le=65535)
    allow_remote: bool = Field(
        default=False,
        description="Permit binding MCP HTTP outside loopback (requires explicit opt-in)",
    )


class VizConfig(BaseModel):
    """Browser viz / WebLLM preferences (prefers local weight cache when present)."""

    webllm_model: str = Field(
        default="Llama-3.2-1B-Instruct-q4f16_1-MLC",
        description="Preferred WebLLM model id for Ask-your-brain chat",
    )
    webllm_prefetch: bool = Field(
        default=True,
        description="Whether wizard/setup should offer prefetching model weights",
    )


class BrainConfig(BaseModel):
    """Validated per-project brain configuration."""

    version: int = Field(default=1, ge=1)
    project_roots: list[str] = Field(default_factory=lambda: ["."])
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    capture: CaptureConfig = Field(default_factory=CaptureConfig)
    injection: InjectionConfig = Field(default_factory=InjectionConfig)
    learning: LearningConfig = Field(default_factory=LearningConfig)
    recall: RecallConfig = Field(default_factory=RecallConfig)
    handover: HandoverConfig = Field(default_factory=HandoverConfig)
    graph: GraphConfig = Field(default_factory=GraphConfig)
    graphify: GraphifyConfig = Field(default_factory=GraphifyConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    groq: GroqConfig = Field(default_factory=GroqConfig)
    viz: VizConfig = Field(default_factory=VizConfig)
    semantic: SemanticConfig | bool = Field(default_factory=SemanticConfig)
    compression: CompressionConfig = Field(default_factory=CompressionConfig)
    decay: DecayConfig = Field(default_factory=DecayConfig)
    git: GitConfig = Field(default_factory=GitConfig)
    team: TeamConfig = Field(default_factory=TeamConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)

    @field_validator("project_roots")
    @classmethod
    def validate_project_roots(cls, roots: list[str]) -> list[str]:
        if not roots:
            msg = "project_roots must contain at least one path"
            raise ValueError(msg)
        normalized = [root.strip() for root in roots if root.strip()]
        if not normalized:
            msg = "project_roots must contain at least one non-empty path"
            raise ValueError(msg)
        return normalized

    @model_validator(mode="before")
    @classmethod
    def coerce_legacy_semantic(cls, data: object) -> object:
        """Accept legacy ``\"semantic\": true|false`` boolean from older configs."""
        if isinstance(data, dict) and isinstance(data.get("semantic"), bool):
            data = {**data, "semantic": {"enabled": data["semantic"]}}
        return data

    def semantic_enabled(self) -> bool:
        if isinstance(self.semantic, bool):
            return self.semantic
        return self.semantic.enabled

    def semantic_config(self) -> SemanticConfig:
        if isinstance(self.semantic, SemanticConfig):
            return self.semantic
        return SemanticConfig(enabled=bool(self.semantic))

    def brain_dir_relative(self) -> str:
        return ".brain"
