"""Secret redaction and prompt-injection scanning before neuron persistence."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from brainkm.logging_config import get_logger

logger = get_logger("adapters.redaction")

ScanMode = Literal["remember", "capture"]


class ScanAction(StrEnum):
    ALLOW = "allow"
    STRIP = "strip"
    BLOCK = "block"


class RedactionBlockedError(Exception):
    """Raised when content must not be stored."""

    def __init__(self, message: str, *, findings: list[RedactionFinding]) -> None:
        super().__init__(message)
        self.findings = findings


@dataclass(frozen=True)
class RedactionFinding:
    category: str
    label: str
    action: ScanAction


@dataclass
class SanitizeResult:
    title: str
    content: str
    blocked: bool = False
    block_reason: str | None = None
    findings: list[RedactionFinding] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _PatternRule:
    category: str
    label: str
    pattern: re.Pattern[str]
    action: ScanAction


SECRET_BLOCK_RULES: tuple[_PatternRule, ...] = (
    _PatternRule(
        "secret",
        "openai_api_key",
        re.compile(r"\bsk-(?:live|test)-[A-Za-z0-9]{10,}\b"),
        ScanAction.BLOCK,
    ),
    _PatternRule(
        "secret",
        "generic_sk_prefix",
        re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
        ScanAction.BLOCK,
    ),
    _PatternRule(
        "secret",
        "aws_access_key",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        ScanAction.BLOCK,
    ),
    _PatternRule(
        "secret",
        "dotenv_block",
        re.compile(
            r"(?ms)^(?:export\s+)?[A-Z][A-Z0-9_]{1,64}="
            r"(?:[^\n\\]|\\.)+(?:\n(?:export\s+)?[A-Z][A-Z0-9_]{1,64}=(?:[^\n\\]|\\.)+){2,}"
        ),
        ScanAction.BLOCK,
    ),
)

SECRET_STRIP_RULES: tuple[_PatternRule, ...] = (
    _PatternRule(
        "secret",
        "bearer_token",
        re.compile(r"\bBearer\s+[A-Za-z0-9\-._~+/]+=*\b", re.IGNORECASE),
        ScanAction.STRIP,
    ),
    _PatternRule(
        "secret",
        "authorization_header",
        re.compile(r"(?im)^Authorization:\s*[^\n]+$"),
        ScanAction.STRIP,
    ),
    _PatternRule(
        "secret",
        "long_base64_blob",
        re.compile(r"[A-Za-z0-9+/]{200,}={0,2}"),
        ScanAction.STRIP,
    ),
)

INJECTION_BLOCK_RULES: tuple[_PatternRule, ...] = (
    _PatternRule(
        "injection",
        "instruction_override",
        re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions", re.IGNORECASE),
        ScanAction.BLOCK,
    ),
    _PatternRule(
        "injection",
        "disregard_above",
        re.compile(r"disregard\s+(?:the\s+)?above", re.IGNORECASE),
        ScanAction.BLOCK,
    ),
    _PatternRule(
        "injection",
        "role_hijack_you_are_now",
        re.compile(r"\byou\s+are\s+now\b", re.IGNORECASE),
        ScanAction.BLOCK,
    ),
    _PatternRule(
        "injection",
        "role_hijack_act_as",
        # Require an agent/assistant framing to avoid false positives like
        # "act as middleware" in technical prose.
        re.compile(
            r"\bact\s+as\s+(?:an?\s+)?(?:ai|assistant|chatbot|system)\b",
            re.IGNORECASE,
        ),
        ScanAction.BLOCK,
    ),
    _PatternRule(
        "injection",
        "new_system_prompt",
        re.compile(r"\bnew\s+system\s+prompt\b", re.IGNORECASE),
        ScanAction.BLOCK,
    ),
)

INJECTION_STRIP_RULES: tuple[_PatternRule, ...] = (
    _PatternRule(
        "injection",
        "system_close_tag",
        re.compile(r"</system>", re.IGNORECASE),
        ScanAction.STRIP,
    ),
    _PatternRule(
        "injection",
        "inst_delimiter",
        re.compile(r"\[INST\]", re.IGNORECASE),
        ScanAction.STRIP,
    ),
    _PatternRule(
        "injection",
        "sys_delimiter",
        re.compile(r"<<SYS>>", re.IGNORECASE),
        ScanAction.STRIP,
    ),
)


def _apply_strip_rules(
    text: str,
    rules: tuple[_PatternRule, ...],
) -> tuple[str, list[RedactionFinding]]:
    findings: list[RedactionFinding] = []
    cleaned = text
    for rule in rules:
        if rule.pattern.search(cleaned):
            findings.append(RedactionFinding(rule.category, rule.label, rule.action))
            cleaned = rule.pattern.sub("", cleaned)
    return cleaned, findings


def _find_block_matches(
    text: str,
    rules: tuple[_PatternRule, ...],
) -> list[RedactionFinding]:
    findings: list[RedactionFinding] = []
    for rule in rules:
        if rule.pattern.search(text):
            findings.append(RedactionFinding(rule.category, rule.label, rule.action))
    return findings


def sanitize_for_storage(
    title: str,
    content: str,
    *,
    source: str | None = None,
    mode: ScanMode = "remember",
) -> SanitizeResult:
    """Scan and sanitize neuron title/body before INSERT.

    Secrets and prompt-injection patterns are always enforced (no source override).
    """
    del mode  # remember and capture share rules in V1
    del source  # reserved for audit context; not used as an override
    combined = f"{title}\n{content}"
    findings: list[RedactionFinding] = []
    warnings: list[str] = []

    secret_blocks = _find_block_matches(combined, SECRET_BLOCK_RULES)
    if secret_blocks:
        reason = "Secret pattern detected; memory not stored"
        logger.warning("%s (%d finding(s))", reason, len(secret_blocks))
        return SanitizeResult(
            title=title,
            content=content,
            blocked=True,
            block_reason=reason,
            findings=secret_blocks,
            warnings=warnings,
        )

    injection_blocks = _find_block_matches(combined, INJECTION_BLOCK_RULES)
    if injection_blocks:
        reason = "Prompt injection pattern detected; memory not stored"
        logger.warning("%s (%d finding(s))", reason, len(injection_blocks))
        return SanitizeResult(
            title=title,
            content=content,
            blocked=True,
            block_reason=reason,
            findings=injection_blocks,
            warnings=warnings,
        )

    cleaned_title, title_secret_strips = _apply_strip_rules(title, SECRET_STRIP_RULES)
    cleaned_content, content_secret_strips = _apply_strip_rules(content, SECRET_STRIP_RULES)
    findings.extend(title_secret_strips)
    findings.extend(content_secret_strips)

    cleaned_title, title_injection_strips = _apply_strip_rules(
        cleaned_title, INJECTION_STRIP_RULES
    )
    cleaned_content, content_injection_strips = _apply_strip_rules(
        cleaned_content, INJECTION_STRIP_RULES
    )
    findings.extend(title_injection_strips)
    findings.extend(content_injection_strips)

    for finding in findings:
        if finding.action is ScanAction.STRIP:
            warnings.append(f"Stripped {finding.category}:{finding.label}")

    cleaned_title = cleaned_title.strip()
    cleaned_content = cleaned_content.strip()

    if title.strip() and not cleaned_title:
        return SanitizeResult(
            title=title,
            content=content,
            blocked=True,
            block_reason="Content reduced to empty after redaction",
            findings=findings,
            warnings=warnings,
        )

    if not cleaned_content and content.strip():
        return SanitizeResult(
            title=title,
            content=content,
            blocked=True,
            block_reason="Content reduced to empty after redaction",
            findings=findings,
            warnings=warnings,
        )

    return SanitizeResult(
        title=cleaned_title if title.strip() else title,
        content=cleaned_content,
        findings=findings,
        warnings=warnings,
    )


def sanitize_capture_text(content: str) -> SanitizeResult:
    """Sanitize transcript or distill chunk text before capture persistence."""
    return sanitize_for_storage("", content, mode="capture")


def scan(title: str, content: str, *, source: str | None = None) -> SanitizeResult:
    """Alias for sanitize_for_storage — inspect without raising."""
    return sanitize_for_storage(title, content, source=source)


def require_clean(title: str, content: str, *, source: str | None = None) -> SanitizeResult:
    """Sanitize and raise RedactionBlockedError when content must not be stored."""
    result = sanitize_for_storage(title, content, source=source)
    if result.blocked:
        raise RedactionBlockedError(
            result.block_reason or "Content blocked by redaction policy",
            findings=result.findings,
        )
    return result
