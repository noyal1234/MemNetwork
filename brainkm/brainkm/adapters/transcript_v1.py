"""Cursor agent-transcripts JSONL parser with format detection."""

from __future__ import annotations

import json
from pathlib import Path

from brainkm.models.distill import ParsedTranscript, TranscriptMessage, TranscriptRound

CURSOR_V1_MAGIC = "cursor_transcript_v1"
SUPPORTED_FORMATS = frozenset({CURSOR_V1_MAGIC, "raw_text"})


def detect_transcript_format(lines: list[str]) -> str:
    """Detect transcript format from the first non-empty line."""
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            return "raw_text"

        if isinstance(payload, dict):
            explicit = payload.get("transcriptFormat") or payload.get("format")
            if explicit == CURSOR_V1_MAGIC:
                return CURSOR_V1_MAGIC
            if "role" in payload and "message" in payload:
                return CURSOR_V1_MAGIC
        return "raw_text"
    return "raw_text"


def _extract_message_text(message_obj: object) -> str:
    if not isinstance(message_obj, dict):
        return str(message_obj)

    content = message_obj.get("content")
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and block.get("text"):
                parts.append(str(block["text"]).strip())
            elif block.get("type") == "tool_use":
                name = block.get("name", "tool")
                parts.append(f"[tool_use:{name}]")
        return "\n".join(part for part in parts if part)

    return ""


def parse_cursor_v1_lines(
    lines: list[str],
    *,
    session_id: str,
    source_path: str | None = None,
) -> ParsedTranscript:
    messages: list[TranscriptMessage] = []
    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue

        role = str(payload.get("role", "unknown"))
        text = _extract_message_text(payload.get("message", {}))
        if not text:
            continue
        messages.append(TranscriptMessage(role=role, text=text, line_no=line_no))

    rounds = _decompose_rounds(messages)
    return ParsedTranscript(
        session_id=session_id,
        format_name=CURSOR_V1_MAGIC,
        messages=tuple(messages),
        rounds=rounds,
        source_path=source_path,
    )


def parse_raw_text(
    text: str,
    *,
    session_id: str,
    source_path: str | None = None,
) -> ParsedTranscript:
    """Fallback parser when JSONL structure is unknown."""
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    if not paragraphs:
        paragraphs = [text.strip()] if text.strip() else []

    messages = [
        TranscriptMessage(role="unknown", text=paragraph, line_no=index + 1)
        for index, paragraph in enumerate(paragraphs)
    ]
    rounds = tuple(
        TranscriptRound(round_index=index, messages=(message,))
        for index, message in enumerate(messages)
    )
    return ParsedTranscript(
        session_id=session_id,
        format_name="raw_text",
        messages=tuple(messages),
        rounds=rounds,
        source_path=source_path,
    )


def _decompose_rounds(messages: list[TranscriptMessage]) -> tuple[TranscriptRound, ...]:
    rounds: list[TranscriptRound] = []
    current: list[TranscriptMessage] = []

    for message in messages:
        if message.role == "user" and current:
            rounds.append(TranscriptRound(round_index=len(rounds), messages=tuple(current)))
            current = [message]
        else:
            current.append(message)

    if current:
        rounds.append(TranscriptRound(round_index=len(rounds), messages=tuple(current)))

    return tuple(rounds)


def parse_transcript_file(
    path: Path,
    *,
    session_id: str | None = None,
) -> ParsedTranscript:
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    resolved_session = session_id or path.stem
    fmt = detect_transcript_format(lines)

    if fmt == CURSOR_V1_MAGIC:
        return parse_cursor_v1_lines(lines, session_id=resolved_session, source_path=str(path))
    return parse_raw_text(raw, session_id=resolved_session, source_path=str(path))
