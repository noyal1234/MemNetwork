"""Capture pipeline helpers — security gate before chunk/neuron persistence."""

from __future__ import annotations

from dataclasses import dataclass

from brainkm.adapters.redaction import RedactionBlockedError, SanitizeResult, sanitize_capture_text


@dataclass(frozen=True)
class CaptureChunk:
    content: str
    role: str | None = None
    session_id: str | None = None


@dataclass(frozen=True)
class PreparedCapture:
    chunk: CaptureChunk
    sanitize_result: SanitizeResult


def prepare_capture_chunk(chunk: CaptureChunk) -> PreparedCapture:
    """Run injection scanner + secret redaction on a transcript chunk."""
    result = sanitize_capture_text(chunk.content)
    if result.blocked:
        raise RedactionBlockedError(
            result.block_reason or "Capture chunk blocked by redaction policy",
            findings=result.findings,
        )

    cleaned = CaptureChunk(
        content=result.content,
        role=chunk.role,
        session_id=chunk.session_id,
    )
    return PreparedCapture(chunk=cleaned, sanitize_result=result)
