"""RTK-inspired tool-log compression with mandatory tee on failure-shaped output."""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

from brainkm.services.compression.types import StageResult
from brainkm.services.memory import token_count

_ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
_PROGRESS = re.compile(
    r"(?i)^(enumerating|counting|compressing|writing objects|download|installing|"
    r"collecting|building wheel|running \d+ tests).*"
)
# Whole-log failure detector (tee trigger). Kept broad on purpose.
_FAIL_MARK = re.compile(
    r"(?i)\b(fail(ed|ure)?|error|traceback|exception|panic|assert|"
    r"✗|✘|FAILED|ERROR)\b"
)
# Per-line: never collapse a line that itself looks like a failure/error.
_LINE_FAIL = re.compile(
    r"(?i)\b(FAILED|ERROR|FAIL|traceback|exception|panic|assertionerror|"
    r"✗|✘|error:)\b"
)
# Per-line collapsible passes only (not summary lines like "2 failed, 18 passed in").
_PASS_LINE = re.compile(
    r"(?ix)^(?:"
    r"ok\b.*"  # bare ok / ok <hash>
    r"|passed"  # bare PASSED
    r"|[✓✔]\s+\S.*"  # jest/vitest checkmark result
    r"|\.+"  # unittest dots-only progress
    # unittest test_a ... ok  |  cargo test foo::bar ... ok
    r"|test(?:\s+\S+|\S*)\s+\.\.\.\s+ok\b.*"
    # pytest verbose: path::node PASSED  or  path::node PASSED [ 5%]
    r"|(?=.*::).*\bPASSED(?:\s*\[\s*\d+%\s*\])?"
    r")\s*$"
)
# Summary / banner lines that mention "passed" but must stay (counts, timing).
_PASS_SUMMARY = re.compile(
    r"(?i)(passed in\b|\bfailed,\s*\d+\s*passed\b|\d+\s+passed,\s*\d+\s+failed"
    r"|short test summary|test session starts|collected\s+\d+)"
)


def _is_collapsible_pass_line(line: str) -> bool:
    """True for individual passing test rows — never summaries or fail rows."""
    s = line.strip()
    if not s or _LINE_FAIL.search(s) or _PASS_SUMMARY.search(s):
        return False
    return bool(_PASS_LINE.match(s))


def looks_like_tool_log(text: str) -> bool:
    if not text or len(text) < 80:
        return False
    lines = text.splitlines()
    if len(lines) < 4:
        return False
    signals = 0
    for line in lines[:40]:
        low = line.lower()
        if low.startswith(("diff --git", "+++", "---", "@@")):
            signals += 2
        if "passed" in low or "failed" in low or "error" in low:
            signals += 1
        if low.startswith(("ok ", "test ", "collecting", "running ")):
            signals += 1
        if "\x1b[" in line:
            signals += 1
    return signals >= 2


def _tee_dir(project_dir: Path | None) -> Path:
    root = project_dir if project_dir is not None else Path.cwd()
    path = root / ".brain" / "tee"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_tee(raw: str, *, project_dir: Path | None = None, label: str = "tool") -> str:
    digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:12]
    stamp = int(time.time())
    path = _tee_dir(project_dir) / f"{stamp}_{label}_{digest}.log"
    path.write_text(raw, encoding="utf-8", errors="replace")
    # Prefer a short project-relative pointer in compressed text.
    if project_dir is not None:
        try:
            return str(path.resolve().relative_to(Path(project_dir).resolve()))
        except ValueError:
            pass
    return str(path)


def compress_tool_log(
    text: str,
    *,
    project_dir: Path | None = None,
    max_lines: int = 80,
) -> StageResult:
    """Compress tool/test/git-shaped output; tee full raw when failure-shaped."""
    t0 = time.perf_counter()
    tokens_in = token_count(text)
    cleaned = _ANSI.sub("", text)
    lines = cleaned.splitlines()
    failure = bool(_FAIL_MARK.search(cleaned))
    tee_path: str | None = None
    if failure:
        tee_path = write_tee(text, project_dir=project_dir, label="fail")

    kept: list[str] = []
    pass_count = 0
    for line in lines:
        stripped = line.rstrip()
        s = stripped.strip()
        if not s:
            continue
        if _PROGRESS.match(s):
            continue
        # Collapse individual passes even when the log also has failures
        # (failures-only view). Summaries / fail rows are never collapsed.
        if _is_collapsible_pass_line(s):
            pass_count += 1
            continue
        kept.append(stripped)

    if pass_count:
        kept.insert(0, f"[ok collapsed: {pass_count} passing lines]")

    # Deduplicate consecutive identical lines
    deduped: list[str] = []
    prev = None
    repeat = 0
    for line in kept:
        if line == prev:
            repeat += 1
            continue
        if repeat:
            deduped.append(f"  … ×{repeat + 1}")
            repeat = 0
        deduped.append(line)
        prev = line
    if repeat:
        deduped.append(f"  … ×{repeat + 1}")

    if len(deduped) > max_lines:
        head = deduped[: max_lines - 12]
        tail = deduped[-10:]
        deduped = head + [f"[… {len(deduped) - len(head) - len(tail)} lines omitted …]"] + tail

    # Guard against the compressed body, not the mandatory tee pointer.
    # Tee paths are long and would otherwise undo pass-collapse on small logs.
    body = "\n".join(deduped).strip() or text.strip()
    skipped = None
    if token_count(body) >= tokens_in:
        body = text
        skipped = "inflation_guard"
    if failure and tee_path:
        out = f"{body.rstrip()}\n[full output: {tee_path}]"
    else:
        out = body
    tokens_out = token_count(out)
    return StageResult(
        engine_id="rtk_lite",
        text=out,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        skipped_reason=skipped,
        latency_ms=(time.perf_counter() - t0) * 1000.0,
        tee_path=tee_path,
    )
