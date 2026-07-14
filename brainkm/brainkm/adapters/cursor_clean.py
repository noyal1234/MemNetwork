"""Clean Cursor transcript chrome before distill."""

from __future__ import annotations

import re

from brainkm.models.distill import TranscriptMessage, TranscriptRound

_USER_QUERY = re.compile(
    r"<user_query>\s*(.*?)\s*</user_query>",
    re.IGNORECASE | re.DOTALL,
)
_TIMESTAMP = re.compile(r"<timestamp>.*?</timestamp>", re.IGNORECASE | re.DOTALL)
_TOOL_USE_LINE = re.compile(r"^\s*\[tool_use:[^\]]+\]\s*$", re.IGNORECASE | re.MULTILINE)
_TOOL_USE_INLINE = re.compile(r"\[tool_use:[^\]]+\]", re.IGNORECASE)
_ROLE_PREFIX = re.compile(r"^(?:USER|ASSISTANT|SYSTEM|TOOL)\s*:\s*", re.IGNORECASE)
_XML_TAG = re.compile(r"</?(?:user_query|timestamp)[^>]*>", re.IGNORECASE)
_BOILERPLATE_LEAD = re.compile(
    r"^(?:i(?:'|’)?ll|i will|let me|i can|sure[,.]?|okay[,.]?|got it[,.]?)\b",
    re.IGNORECASE,
)


def extract_user_query(text: str) -> str | None:
    """Return inner <user_query> text when present."""
    match = _USER_QUERY.search(text)
    if not match:
        return None
    return match.group(1).strip()


def clean_cursor_text(text: str) -> str:
    """Strip Cursor XML chrome, role prefixes, and tool_use markers."""
    if not text:
        return ""

    extracted = extract_user_query(text)
    cleaned = extracted if extracted is not None else text
    cleaned = _TIMESTAMP.sub("", cleaned)
    cleaned = _TOOL_USE_LINE.sub("", cleaned)
    cleaned = _TOOL_USE_INLINE.sub("", cleaned)
    cleaned = _XML_TAG.sub("", cleaned)

    lines: list[str] = []
    for line in cleaned.splitlines():
        stripped = _ROLE_PREFIX.sub("", line).strip()
        if not stripped or stripped.lower().startswith("[tool_use:"):
            continue
        lines.append(stripped)

    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def is_distill_noise(text: str) -> bool:
    """True for fragments that must never become neurons."""
    stripped = text.strip()
    if len(stripped) < 20:
        return True
    lowered = stripped.lower()
    if "[tool_use:" in lowered:
        return True
    if "<user_query>" in lowered or "</user_query>" in lowered:
        return True
    if "<timestamp>" in lowered:
        return True
    if _ROLE_PREFIX.match(stripped):
        return True
    if _BOILERPLATE_LEAD.match(stripped) and len(stripped) < 80:
        return True
    return False


def distillable_round(round_: TranscriptRound) -> TranscriptRound | None:
    """Return a round with cleaned message text, or None if empty after cleaning."""
    messages: list[TranscriptMessage] = []
    for message in round_.messages:
        cleaned = clean_cursor_text(message.text)
        if not cleaned or is_distill_noise(cleaned):
            continue
        messages.append(
            TranscriptMessage(
                role=message.role,
                text=cleaned,
                line_no=message.line_no,
            )
        )
    if not messages:
        return None
    return TranscriptRound(round_index=round_.round_index, messages=tuple(messages))
