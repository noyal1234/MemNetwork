"""Models for PreCompact handover."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PreCompactHookPayload:
    transcript_path: Path
    session_id: str | None
    conversation_id: str | None


@dataclass(frozen=True)
class HandoverResult:
    session_id: str
    skipped: bool
    reason: str | None
    chunk_count: int
    neuron_count: int
    distill_mode: str
    export_path: Path | None
    checkpoint_ok: bool
