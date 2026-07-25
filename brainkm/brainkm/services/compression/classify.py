"""Content-class routing (top-level + sub-block hints)."""

from __future__ import annotations

import re

from brainkm.services.compression.rtk_lite import looks_like_tool_log
from brainkm.services.compression.types import ContentClass

_ERROR_HEAD = re.compile(r"(?i)^(error|exception|traceback|panic|failed)\b")
_CODE_HEAVY = re.compile(r"```|^\s{2,}(def |class |function |import )", re.MULTILINE)


def classify_content(
    text: str,
    *,
    kind: str | None = None,
    subtype: str | None = None,
) -> ContentClass:
    """Top-level class from object model first, then heuristics."""
    if kind == "procedure":
        return "procedure"
    if kind == "memory":
        if subtype == "decision":
            return "decision"
        if subtype == "rule":
            return "rule"
        if subtype == "error":
            return "error"
        if subtype == "observation":
            if looks_like_tool_log(text):
                return "tool_log"
            return "observation"
        if subtype in {"context", "episode", "fact", "pattern"}:
            if looks_like_tool_log(text):
                return "tool_log"
            return "prose"
    if looks_like_tool_log(text):
        return "tool_log"
    if _ERROR_HEAD.search((text or "").lstrip()[:80]):
        return "error"
    if _CODE_HEAVY.search(text or ""):
        return "code_ref"
    return "prose"


_LOG_BLOCK = re.compile(
    r"(?ms)^(?:```(?:text|log|bash|shell)?\n)?("
    r"(?:.*(?:FAILED|ERROR|Traceback|diff --git).*\n){2,}"
    r")(?:```)?"
)


def split_subblocks(text: str) -> list[tuple[ContentClass, str]]:
    """Split text into (class, segment) for mixed decision+log bodies."""
    if not text:
        return [("prose", "")]
    blocks: list[tuple[ContentClass, str]] = []
    cursor = 0
    for match in _LOG_BLOCK.finditer(text):
        if match.start() > cursor:
            pre = text[cursor : match.start()]
            if pre.strip():
                blocks.append(("prose", pre))
        blocks.append(("tool_log", match.group(0)))
        cursor = match.end()
    if cursor < len(text):
        tail = text[cursor:]
        if tail.strip() or not blocks:
            blocks.append(("prose", tail))
    if not blocks:
        return [("prose", text)]
    return blocks
