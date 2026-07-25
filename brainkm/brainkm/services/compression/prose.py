"""Caveman-inspired prose condensation (lite/full) with protect-span restore."""

from __future__ import annotations

import re
import time

from brainkm.services.compression.protect import mask_protected, unmask_protected
from brainkm.services.compression.types import ProseIntensity, StageResult
from brainkm.services.memory import token_count

_FILLER = re.compile(
    r"(?i)\b("
    r"basically|actually|really|just|simply|obviously|clearly|certainly|"
    r"I(?:'d| would) (?:be happy to|recommend|suggest)|"
    r"it(?:'s| is) (?:important|worth) (?:to|noting)|"
    r"as (?:you )?(?:can|may) (?:see|know)|"
    r"in order to|the reason (?:is|why)|"
    r"please note that|keep in mind that|"
    r"going forward|at the end of the day"
    r")\b[,\s]*"
)
_HEDGE = re.compile(
    r"(?i)\b(might|maybe|perhaps|somewhat|rather|quite|very|pretty much)\b\s*"
)
_MULTI_SPACE = re.compile(r"[ \t]{2,}")
_MULTI_NL = re.compile(r"\n{3,}")


def condense_prose(
    text: str,
    *,
    intensity: ProseIntensity = "lite",
) -> StageResult:
    t0 = time.perf_counter()
    tokens_in = token_count(text)
    if intensity == "off" or not text.strip():
        return StageResult(
            engine_id="prose_condense",
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_in,
            skipped_reason="intensity_off" if intensity == "off" else "empty",
            latency_ms=(time.perf_counter() - t0) * 1000.0,
        )

    masked, originals = mask_protected(text)
    out = _FILLER.sub("", masked)
    if intensity == "full":
        out = _HEDGE.sub("", out)
    out = _MULTI_SPACE.sub(" ", out)
    out = _MULTI_NL.sub("\n\n", out)
    # Drop empty hedging sentences left as fragments
    lines = []
    for line in out.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        if intensity == "full" and len(stripped.split()) <= 2 and stripped.endswith("."):
            continue
        lines.append(line.rstrip())
    out = "\n".join(lines).strip()
    out = unmask_protected(out, originals)
    tokens_out = token_count(out)
    skipped = None
    if tokens_out >= tokens_in or not out:
        out = text
        tokens_out = tokens_in
        skipped = "inflation_guard"
    return StageResult(
        engine_id="prose_condense",
        text=out,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        skipped_reason=skipped,
        latency_ms=(time.perf_counter() - t0) * 1000.0,
    )
