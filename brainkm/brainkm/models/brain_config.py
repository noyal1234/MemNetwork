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


class BudgetConfig(BaseModel):
    total_tokens: int = Field(default=1500, ge=100, le=8000)
    dynamic_reallocation: bool = True
    session_start: SessionStartBudget = Field(default_factory=SessionStartBudget)
    pre_tool: PreToolBudget = Field(default_factory=PreToolBudget)


class CaptureConfig(BaseModel):
    transcripts: bool = True
    plan_files: bool = True
    plan_glob: str = ".cursor/plans/*.plan.md"
    distill_mode: Literal["cursor", "ollama", "rules"] = "cursor"
    max_auto_neurons_per_session: int = Field(default=50, ge=1, le=500)
    max_neurons_per_plan: int = Field(default=20, ge=1, le=200)


class InjectionConfig(BaseModel):
    session_start: bool = True
    pre_tool_patterns: list[str] = Field(
        default_factory=lambda: ["write", "edit", "run_terminal"]
    )
    max_recalls_per_turn: int = Field(default=1, ge=0, le=5)
    frozen_snapshot: bool = True


class LearningConfig(BaseModel):
    co_activation_threshold: int = Field(default=3, ge=1)
    max_tool_nodes: int = Field(default=20, ge=1, le=50)
    auto_capture_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    session_window_size: int = Field(default=20, ge=5, le=100)


class RecallConfig(BaseModel):
    abstain_on_low_confidence: bool = True
    abstain_mode: Literal["percentile", "absolute"] = "percentile"
    abstain_percentile: float = Field(default=0.25, ge=0.0, le=1.0)
    min_recall_score: float | None = Field(default=None, ge=0.0, le=100.0)

    @model_validator(mode="after")
    def absolute_mode_requires_threshold(self) -> RecallConfig:
        if self.abstain_mode == "absolute" and self.min_recall_score is None:
            msg = "min_recall_score is required when abstain_mode is 'absolute'"
            raise ValueError(msg)
        return self


class HandoverConfig(BaseModel):
    precompact_enabled: bool = True
    precompact_distill_timeout_seconds: int = Field(default=5, ge=1, le=60)
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
    model: str = "llama3.2:3b"
    timeout_seconds: int = Field(default=120, ge=5, le=600)


class GitConfig(BaseModel):
    enabled: bool = False


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
    semantic: bool = False
    git: GitConfig = Field(default_factory=GitConfig)

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

    def brain_dir_relative(self) -> str:
        return ".brain"
