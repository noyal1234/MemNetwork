"""Pydantic models for MCP tool I/O."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class NeuronResult(BaseModel):
    node_id: str
    kind: str
    subtype: str | None = None
    title: str
    content: str | None = None
    score: float | None = None
    activation: float | None = None


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


class ContextPackRequest(BaseModel):
    query: str = Field(..., min_length=1)
    session_id: str | None = None


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


class SessionStatusRequest(BaseModel):
    session_id: str | None = None
    title: str | None = None
    body: str | None = None


class SessionStatusResponse(BaseModel):
    node_id: str | None = None
    title: str | None = None
    body: str | None = None
    updated: bool = False


class TraverseRequest(BaseModel):
    from_ref: str = Field(..., description="Node ID, file path, or symbol name")
    to_ref: str | None = Field(None, description="Target; omit for 1-hop neighborhood")
    max_hops: int = Field(default=1, ge=1, le=2)
    relationship: str | None = Field(None, description="Filter: imports|calls|supersedes|...")
    direction: Literal["out", "in", "both"] = "out"


class TraverseResponse(BaseModel):
    from_ref: str
    nodes: list[NeuronResult]
    hops_explored: int = 0


class ForgetRequest(BaseModel):
    node_id: str = Field(..., min_length=1)
    reason: str | None = None


class ForgetResponse(BaseModel):
    node_id: str
    archived: bool
    valid_until: str | None = None
