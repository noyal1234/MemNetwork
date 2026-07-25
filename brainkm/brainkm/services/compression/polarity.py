"""Polarity-scoped decision/rule egress rubric (deterministic, CI ≈ $0)."""

from __future__ import annotations

import re
from dataclasses import dataclass

_NEG_CLAUSE = re.compile(
    r"(?i)\b(?P<neg>must not|never|do not|don't|cannot|no longer|instead of)\b"
    r"(?P<body>[^.!?\n]{0,100})"
)
_OBLIGATION = re.compile(r"(?i)\b(must|never|always|prefer|reject)\b")


@dataclass(frozen=True)
class RubricCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class RubricResult:
    checks: list[RubricCheck]
    score: float  # 0..1
    gold_checks: int

    @property
    def pct_of_baseline(self) -> float:
        return self.score * 100.0


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def extract_polarity_clauses(text: str) -> list[tuple[str, str]]:
    """Return list of (negation_marker, bound_body_snippet)."""
    out: list[tuple[str, str]] = []
    for match in _NEG_CLAUSE.finditer(text or ""):
        neg = match.group("neg").lower()
        body = match.group("body").strip()
        # Bind object-ish tokens
        words = re.findall(r"[a-z0-9_./-]{3,}", body.lower())
        obj = " ".join(words[:6])
        out.append((neg, obj))
    return out


def grade_egress(full_body: str, egress: str) -> RubricResult:
    """Grade egress against full-body gold with polarity co-location."""
    checks: list[RubricCheck] = []
    gold_clauses = extract_polarity_clauses(full_body)
    egress_norm = _normalize(egress)
    full_norm = _normalize(full_body)

    for neg, obj in gold_clauses:
        # Negation must appear near object tokens in egress
        if not obj:
            present = neg in egress_norm
            checks.append(
                RubricCheck(
                    name=f"neg:{neg}",
                    passed=present,
                    detail="negation present" if present else "negation missing",
                )
            )
            continue
        # Windowed: negation and first object token within ~80 chars
        pattern = re.compile(
            rf"(?i){re.escape(neg)}.{{0,80}}{re.escape(obj.split()[0])}"
            rf"|{re.escape(obj.split()[0])}.{{0,80}}{re.escape(neg)}"
        )
        ok = bool(pattern.search(egress))
        # Fail if object present but negation orphaned/absent (polarity invert risk)
        if not ok and obj.split()[0] in egress_norm and neg not in egress_norm:
            ok = False
        checks.append(
            RubricCheck(
                name=f"polarity:{neg}+{obj[:40]}",
                passed=ok,
                detail="co-located" if ok else "polarity broken or missing",
            )
        )

    # Obligation lexicon presence for non-negation must/always when in gold
    for match in _OBLIGATION.finditer(full_body or ""):
        word = match.group(1).lower()
        if word in {"must", "never"} and any(c[0].startswith(word) for c in gold_clauses):
            continue
        ok = word in egress_norm
        checks.append(
            RubricCheck(
                name=f"lexicon:{word}",
                passed=ok,
                detail="present" if ok else "missing",
            )
        )

    # Paths in gold must survive
    for path in re.findall(r"(?:[\w.-]+/)+[\w.-]+\.[a-zA-Z0-9]{1,8}", full_body or ""):
        ok = path in (egress or "")
        checks.append(
            RubricCheck(name=f"path:{path}", passed=ok, detail="path intact" if ok else "path lost")
        )

    if not checks:
        # Trivial pass when gold has no obligations — still require non-empty egress if full non-empty
        ok = (not full_norm) or bool(egress_norm)
        checks.append(RubricCheck(name="nonempty", passed=ok, detail="ok" if ok else "empty egress"))

    passed = sum(1 for c in checks if c.passed)
    score = passed / len(checks) if checks else 1.0
    return RubricResult(checks=checks, score=score, gold_checks=len(checks))


def meets_answerability_bar(
    full_body: str,
    egress: str,
    *,
    min_pct: float = 95.0,
) -> bool:
    result = grade_egress(full_body, egress)
    return result.pct_of_baseline >= min_pct
