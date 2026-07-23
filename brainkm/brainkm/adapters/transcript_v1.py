"""Cursor / Claude / Antigravity agent-transcripts JSONL parser with format detection."""

from __future__ import annotations

import json
import re
from pathlib import Path

from brainkm.models.distill import ParsedTranscript, TranscriptMessage, TranscriptRound

CURSOR_V1_MAGIC = "cursor_transcript_v1"
CLAUDE_JSONL = "claude_jsonl"
ANTIGRAVITY_JSONL = "antigravity_jsonl"
CODEX_JSONL = "codex_jsonl"
SUPPORTED_FORMATS = frozenset(
    {CURSOR_V1_MAGIC, CLAUDE_JSONL, ANTIGRAVITY_JSONL, CODEX_JSONL, "raw_text"}
)

_CLAUDE_TYPES = frozenset({"user", "assistant", "human", "system", "message"})
_AGY_USER_TYPES = frozenset({"USER_INPUT", "USER_EXPLICIT"})
_AGY_ASSISTANT_TYPES = frozenset(
    {"PLANNER_RESPONSE", "AGENT_RESPONSE", "MODEL_RESPONSE", "ASSISTANT_RESPONSE"}
)
_AGY_SKIP_TYPES = frozenset({"CONVERSATION_HISTORY", "EPHEMERAL_MESSAGE"})
_USER_REQUEST_RE = re.compile(
    r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>",
    re.DOTALL | re.IGNORECASE,
)


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
            if explicit in (ANTIGRAVITY_JSONL, "antigravity", "agy"):
                return ANTIGRAVITY_JSONL
            if explicit in (CODEX_JSONL, "codex", "codex_cli"):
                return CODEX_JSONL
            if _looks_like_antigravity(payload):
                return ANTIGRAVITY_JSONL
            if "role" in payload and "message" in payload:
                return CURSOR_V1_MAGIC
            if _looks_like_claude(payload):
                return CLAUDE_JSONL
            if _looks_like_codex(payload):
                return CODEX_JSONL
        return "raw_text"
    return "raw_text"


def _looks_like_antigravity(payload: dict) -> bool:
    step_type = str(payload.get("type") or "")
    if step_type in _AGY_USER_TYPES or step_type in _AGY_ASSISTANT_TYPES:
        return True
    if "step_index" in payload and ("content" in payload or "tool_calls" in payload):
        return True
    return False


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


def _looks_like_codex(payload: dict) -> bool:
    """Defensive detection for Codex rollout / session JSONL (format is unstable)."""
    if payload.get("transcriptFormat") in (CODEX_JSONL, "codex", "codex_cli"):
        return True
    # Common Codex rollout shapes: event/type + payload/item, or role at top.
    event = str(payload.get("type") or payload.get("event") or "").lower()
    if event in {
        "session_meta",
        "sessionmeta",
        "response_item",
        "responseitem",
        "event_msg",
        "eventmsg",
        "turn_context",
        "turncontext",
        "agent_message",
        "user_message",
        "function_call",
        "function_call_output",
        "reasoning",
        "message",
    }:
        return True
    if "payload" in payload and isinstance(payload.get("payload"), dict):
        nested = payload["payload"]
        if nested.get("role") in ("user", "assistant", "system", "tool"):
            return True
        if nested.get("type") in ("message", "function_call", "function_call_output"):
            return True
    if payload.get("role") in ("user", "assistant", "system", "tool") and (
        "content" in payload or "text" in payload
    ):
        # Avoid stealing Cursor's role+message envelope (already checked earlier).
        if "message" not in payload:
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


def _strip_agy_user_request(content: str) -> str:
    match = _USER_REQUEST_RE.search(content)
    if match:
        return match.group(1).strip()
    return content.strip()


def _agy_role_for_type(step_type: str) -> str | None:
    upper = step_type.upper()
    if upper in _AGY_SKIP_TYPES:
        return None
    if upper in _AGY_USER_TYPES or upper == "USER":
        return "user"
    if upper in _AGY_ASSISTANT_TYPES or upper.startswith("PLANNER"):
        return "assistant"
    if (
        "TOOL" in upper
        or upper.endswith("_FILE")
        or upper
        in {
            "RUN_COMMAND",
            "SEARCH_WEB",
            "VIEW_FILE",
            "EDIT_FILE",
            "WRITE_TO_FILE",
            "REPLACE_FILE_CONTENT",
        }
    ):
        return "assistant"
    if upper in {"SYSTEM_MESSAGE", "SYSTEM"}:
        return "system"
    if step_type:
        # Unknown future types: keep as assistant prose when content present.
        return "assistant"
    return None


def parse_antigravity_jsonl_lines(
    lines: list[str],
    *,
    session_id: str,
    source_path: str | None = None,
) -> ParsedTranscript:
    """Parse Antigravity ``transcript.jsonl`` (step_index / type / content)."""
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

        step_type = str(payload.get("type") or "")
        role = _agy_role_for_type(step_type)
        if role is None:
            continue

        content = payload.get("content")
        text = ""
        if isinstance(content, str) and content.strip():
            text = _strip_agy_user_request(content) if role == "user" else content.strip()
        elif payload.get("tool_calls"):
            calls = payload.get("tool_calls")
            if isinstance(calls, list) and calls:
                names = []
                for call in calls[:5]:
                    if isinstance(call, dict):
                        names.append(str(call.get("name") or call.get("tool") or "tool"))
                text = f"[tool_calls:{','.join(names)}]" if names else "[tool_calls]"

        if not text:
            continue
        messages.append(TranscriptMessage(role=role, text=text, line_no=line_no))

    rounds = _decompose_rounds(messages)
    return ParsedTranscript(
        session_id=session_id,
        format_name=ANTIGRAVITY_JSONL,
        messages=tuple(messages),
        rounds=rounds,
        source_path=source_path,
    )


def _codex_text_from_content(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str) and block.strip():
                parts.append(block.strip())
                continue
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "").lower()
            if block_type in {"text", "input_text", "output_text"} and block.get("text"):
                parts.append(str(block["text"]).strip())
            elif block.get("text"):
                parts.append(str(block["text"]).strip())
            elif block_type in {"tool_use", "function_call"}:
                name = block.get("name") or block.get("tool") or "tool"
                parts.append(f"[tool_use:{name}]")
            elif block_type in {"tool_result", "function_call_output"}:
                parts.append("[tool_result]")
        return "\n".join(part for part in parts if part)
    if isinstance(content, dict):
        return _extract_message_text(content)
    return ""


def _codex_role_and_text(payload: dict) -> tuple[str | None, str]:
    """Extract (role, text) from one Codex JSONL record; format may change."""
    nested = payload.get("payload") if isinstance(payload.get("payload"), dict) else None
    item = payload.get("item") if isinstance(payload.get("item"), dict) else None
    source = nested or item or payload

    role = source.get("role") or payload.get("role")
    event = str(payload.get("type") or payload.get("event") or source.get("type") or "").lower()

    if role is None:
        if event in {"user_message", "user"} or "user" in event:
            role = "user"
        elif event in {
            "agent_message",
            "assistant_message",
            "assistant",
            "reasoning",
            "response_item",
            "message",
        }:
            role = "assistant"
        elif "function_call" in event or "tool" in event:
            role = "assistant"
        elif event in {"session_meta", "sessionmeta", "turn_context", "turncontext"}:
            return None, ""

    if role == "human":
        role = "user"
    if role not in ("user", "assistant", "system", "tool"):
        # Unknown future shapes: keep assistant prose when content present.
        if _codex_text_from_content(
            source.get("content") or source.get("text") or payload.get("text")
        ):
            role = "assistant"
        else:
            return None, ""

    text = _codex_text_from_content(
        source.get("content") or source.get("text") or payload.get("content") or payload.get("text")
    )
    if not text and source.get("name"):
        text = f"[tool_use:{source.get('name')}]"
    if not text and source.get("call_id") and "output" in event:
        text = "[tool_result]"
    return str(role), text


def parse_codex_jsonl_lines(
    lines: list[str],
    *,
    session_id: str,
    source_path: str | None = None,
) -> ParsedTranscript:
    """Parse Codex CLI session/rollout JSONL defensively (format is unstable).

    Falls back to extracting any user/assistant/tool text we can find; unknown
    records are skipped rather than failing the whole capture.
    """
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

        role, text = _codex_role_and_text(payload)
        if role is None or not text:
            continue
        messages.append(TranscriptMessage(role=role, text=text, line_no=line_no))

    # If detection was optimistic but nothing parsed, treat as raw paragraphs.
    if not messages:
        return parse_raw_text(
            "\n".join(lines),
            session_id=session_id,
            source_path=source_path,
        )

    rounds = _decompose_rounds(messages)
    return ParsedTranscript(
        session_id=session_id,
        format_name=CODEX_JSONL,
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
        return parse_claude_jsonl_lines(lines, session_id=resolved_session, source_path=str(path))
    if fmt == ANTIGRAVITY_JSONL:
        return parse_antigravity_jsonl_lines(
            lines, session_id=resolved_session, source_path=str(path)
        )
    if fmt == CODEX_JSONL:
        return parse_codex_jsonl_lines(lines, session_id=resolved_session, source_path=str(path))
    return parse_raw_text(raw, session_id=resolved_session, source_path=str(path))
