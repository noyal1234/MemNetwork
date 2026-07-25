"""Shared types for the compression pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class CompositionMode(str, Enum):
    APPEND = "A"
    STABLE = "S"
    REGENERATE = "R"


SurfaceId = Literal[
    "session_start",
    "pre_tool",
    "mcp_tool_result",
    "observe_write",
    "capture_write",
    "handover_write",
    "pack_egress",
    "injection_egress",
]

ContentClass = Literal[
    "tool_log",
    "observation",
    "decision",
    "rule",
    "error",
    "procedure",
    "prose",
    "code_ref",
]

ProseIntensity = Literal["off", "lite", "full"]


ENGINE_VERSION = "1"


@dataclass(frozen=True)
class StageResult:
    engine_id: str
    text: str
    tokens_in: int
    tokens_out: int
    skipped_reason: str | None = None
    latency_ms: float = 0.0
    tee_path: str | None = None


@dataclass
class PipelineResult:
    text: str
    content_class: ContentClass
    stages: list[StageResult] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    tee_path: str | None = None
    engine_version: str = ENGINE_VERSION

    @property
    def saved_tokens(self) -> int:
        return max(0, self.tokens_in - self.tokens_out)
