"""Protected-span extraction — code, URLs, paths, JSON, obligation clauses."""

from __future__ import annotations

import re
from dataclasses import dataclass

_CODE_FENCE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_INLINE_CODE = re.compile(r"`[^`\n]+`")
_URL = re.compile(r"https?://[^\s<>\]\"']+")
_PATH = re.compile(
    r"(?:^|[\s\"'(=])((?:[\w.-]+/)+[\w.-]+\.[a-zA-Z0-9]{1,8}|/[^\s\"']+\.[a-zA-Z0-9]{1,8})"
)
_JSONISH = re.compile(r"\{[^{}]{2,400}\}|\[\[[^\[\]]{2,400}\]\]")
_OBLIGATION = re.compile(
    r"(?i)\b(?:must not|must|never|always|do not|don't|cannot|no longer|instead of)\b[^.!?\n]{0,120}"
)


@dataclass(frozen=True)
class ProtectedSpan:
    start: int
    end: int
    kind: str
    text: str


def find_protected_spans(text: str) -> list[ProtectedSpan]:
    """Return non-overlapping protected spans sorted by start."""
    hits: list[ProtectedSpan] = []
    for kind, pattern in (
        ("code_fence", _CODE_FENCE),
        ("inline_code", _INLINE_CODE),
        ("url", _URL),
        ("path", _PATH),
        ("json", _JSONISH),
        ("obligation", _OBLIGATION),
    ):
        for match in pattern.finditer(text):
            if kind == "path" and match.lastindex:
                start, end = match.start(1), match.end(1)
                hits.append(ProtectedSpan(start, end, kind, text[start:end]))
            else:
                hits.append(
                    ProtectedSpan(match.start(), match.end(), kind, match.group(0))
                )
    hits.sort(key=lambda span: (span.start, -(span.end - span.start)))
    merged: list[ProtectedSpan] = []
    for span in hits:
        if merged and span.start < merged[-1].end:
            continue
        merged.append(span)
    return merged


def mask_protected(text: str) -> tuple[str, list[str]]:
    """Replace protected spans with placeholders; return (masked, originals)."""
    spans = find_protected_spans(text)
    if not spans:
        return text, []
    parts: list[str] = []
    originals: list[str] = []
    cursor = 0
    for idx, span in enumerate(spans):
        parts.append(text[cursor : span.start])
        placeholder = f"⟦P{idx}⟧"
        parts.append(placeholder)
        originals.append(span.text)
        cursor = span.end
    parts.append(text[cursor:])
    return "".join(parts), originals


def unmask_protected(text: str, originals: list[str]) -> str:
    out = text
    for idx, original in enumerate(originals):
        out = out.replace(f"⟦P{idx}⟧", original)
    return out
