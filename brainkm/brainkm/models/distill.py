"""Models for transcript parsing and distillation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TranscriptMessage:
    role: str
    text: str
    line_no: int


@dataclass(frozen=True)
class TranscriptRound:
    """User turn plus following assistant/tool messages (Mem0-style decomposition)."""

    round_index: int
    messages: tuple[TranscriptMessage, ...]

    @property
    def combined_text(self) -> str:
        parts: list[str] = []
        for message in self.messages:
            prefix = message.role.upper()
            parts.append(f"{prefix}: {message.text}")
        return "\n\n".join(parts)


@dataclass(frozen=True)
class ParsedTranscript:
    session_id: str
    format_name: str
    messages: tuple[TranscriptMessage, ...]
    rounds: tuple[TranscriptRound, ...]
    source_path: str | None = None


@dataclass(frozen=True)
class StoredChunk:
    id: str
    session_id: str
    role: str | None
    content: str
    ts: str
    line_no: int | None = None


@dataclass
class DistilledNeuron:
    subtype: str
    title: str
    body: str
    tags: list[str] = field(default_factory=list)
    chunk_ids: list[str] = field(default_factory=list)
    confidence: float = 1.0

    def is_atomic(self, *, max_body_chars: int = 400) -> bool:
        if len(self.body) > max_body_chars:
            return False
        summary_markers = ("in summary", "to summarize", "overall,", "in conclusion")
        lowered = self.body.lower()
        return not any(marker in lowered for marker in summary_markers)


@dataclass(frozen=True)
class CaptureResult:
    session_id: str
    skipped: bool
    reason: str | None
    chunk_count: int
    neuron_count: int
    distill_mode: str
