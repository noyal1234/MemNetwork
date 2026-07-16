"""Cursor / Claude agent-transcripts JSONL parser with format detection."""

from __future__ import annotations

import json
from pathlib import Path

from brainkm.models.distill import ParsedTranscript, TranscriptMessage, TranscriptRound

CURSOR_V1_MAGIC = "cursor_transcript_v1"
CLAUDE_JSONL = "claude_jsonl"
SUPPORTED_FORMATS = frozenset({CURSOR_V1_MAGIC, CLAUDE_JSONL, "raw_text"})

_CLAUDE_TYPES = frozenset({"user", "assistant", "human", "system", "message"})


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
            if explicit in (CLAUDE_JSONL, "claude", "claude_code"):
                return CLAUDE_JSONL
            if "role" in payload and "message" in payload:
                return CURSOR_V1_MAGIC
            if _looks_like_claude(payload):
                return CLAUDE_JSONL
        return "raw_text"
    return "raw_text"


def _looks_like_claude(payload: dict) -> bool:
    event_type = str(payload.get("type", "")).lower()
    if event_type in _CLAUDE_TYPES and "message" in payload:
        return True
    if event_type in _CLAUDE_TYPES and "content" in payload:
        return True
    # Nested Claude Code shape without top-level role
    message = payload.get("message")
    if isinstance(message, dict) and message.get("role") and "content" in message:
        # Prefer Claude when Cursor envelope (role+message at top) is absent
        if "role" not in payload:
            return True
    return False


def _extract_message_text(message_obj: object) -> str:
    if not isinstance(message_obj, dict):
        if isinstance(message_obj, str):
            return message_obj.strip()
        return str(message_obj) if message_obj is not None else ""

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
            elif block.get("type") == "tool_result":
                parts.append("[tool_result]")
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


def parse_claude_jsonl_lines(
    lines: list[str],
    *,
    session_id: str,
    source_path: str | None = None,
) -> ParsedTranscript:
    """Parse Claude Code session JSONL into the shared transcript model."""
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

        event_type = str(payload.get("type", "")).lower()
        message_obj = payload.get("message")
        role = "unknown"
        text = ""

        if isinstance(message_obj, dict):
            role = str(message_obj.get("role") or event_type or "unknown")
            text = _extract_message_text(message_obj)
        elif "content" in payload:
            role = str(payload.get("role") or event_type or "unknown")
            text = _extract_message_text(payload)
        elif isinstance(message_obj, str):
            role = str(event_type or "unknown")
            text = message_obj.strip()

        if role == "human":
            role = "user"
        if not text:
            continue
        messages.append(TranscriptMessage(role=role, text=text, line_no=line_no))

    rounds = _decompose_rounds(messages)
    return ParsedTranscript(
        session_id=session_id,
        format_name=CLAUDE_JSONL,
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
    if fmt == CLAUDE_JSONL:
        return parse_claude_jsonl_lines(
            lines, session_id=resolved_session, source_path=str(path)
        )
    return parse_raw_text(raw, session_id=resolved_session, source_path=str(path))
