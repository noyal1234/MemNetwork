"""LongMemEval-S retrieval footnote — same protocol as agentmemory (not official QA).

Downloads are optional. Without a dataset path the suite reports a single skipped PASS
so default CI stays free of the ~264MB corpus. When present, reports recall_any@K + MRR.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from brainkm.bench.results import BenchCaseResult, BenchSuiteResult
from brainkm.config import get_settings, set_skip_rolling_scores
from brainkm.models.brain_config import RecallConfig
from brainkm.services.bench_db import (
    cleanup_ephemeral_project,
    ensure_fixture_neuron,
    ephemeral_project_brain,
)
from brainkm.services.recall import recall_live

# Cap session body so ephemeral FTS stays tractable on LongMemEval haystacks.
_MAX_SESSION_CHARS = 4000
_DEFAULT_CACHE = Path.home() / ".cache" / "brainkm" / "longmemeval_s_cleaned.json"
_DOWNLOAD_HINT = (
    "Download LongMemEval-S (cleaned) then set LONGMEMEVAL_PATH or pass --dataset:\n"
    "  pip install huggingface_hub\n"
    "  python -c \"from huggingface_hub import hf_hub_download; "
    "print(hf_hub_download(repo_id='xiaowu0162/longmemeval-cleaned', "
    "filename='longmemeval_s_cleaned.json', repo_type='dataset', "
    "local_dir=str(__import__('pathlib').Path.home()/'.cache'/'brainkm')))\"\n"
    "This suite is a retrieval-only footnote (recall_any@K), not official LongMemEval QA."
)


def resolve_longmemeval_path(explicit: Path | None = None) -> Path | None:
    """Resolve dataset JSON: CLI path > settings LONGMEMEVAL_PATH > default cache."""
    if explicit is not None:
        # Explicit path wins: missing file means skip (do not fall through to cache).
        return explicit if explicit.is_file() else None
    settings = get_settings()
    configured = getattr(settings, "longmemeval_path", None)
    if configured is not None:
        path = Path(configured)
        if path.is_file():
            return path
    if _DEFAULT_CACHE.is_file():
        return _DEFAULT_CACHE
    return None


def _flatten_session(turns: list[dict]) -> str:
    parts: list[str] = []
    for turn in turns:
        role = turn.get("role", "unknown")
        content = turn.get("content") or ""
        parts.append(f"[{role}] {content}")
    text = "\n\n".join(parts)
    if len(text) > _MAX_SESSION_CHARS:
        return text[:_MAX_SESSION_CHARS]
    return text


def load_longmemeval_questions(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        msg = f"LongMemEval dataset must be a JSON list: {path}"
        raise ValueError(msg)
    questions: list[dict] = []
    for row in raw:
        session_ids = list(row.get("haystack_session_ids") or [])
        sessions = list(row.get("haystack_sessions") or [])
        if len(session_ids) != len(sessions):
            continue
        haystack = [
            {"id": sid, "content": _flatten_session(turns)}
            for sid, turns in zip(session_ids, sessions, strict=True)
        ]
        questions.append(
            {
                "id": row.get("question_id") or row.get("id"),
                "type": row.get("question_type") or "unknown",
                "question": row.get("question") or "",
                "gold_session_ids": list(row.get("answer_session_ids") or []),
                "haystack": haystack,
            }
        )
    return questions


def stratify_sample(questions: list[dict], per_type: int) -> list[dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for q in questions:
        buckets[str(q["type"])].append(q)
    out: list[dict] = []
    for qtype in sorted(buckets):
        out.extend(buckets[qtype][:per_type])
    return out


def _mrr(ranked_ids: list[str], gold: set[str]) -> float:
    for i, nid in enumerate(ranked_ids, start=1):
        if nid in gold:
            return 1.0 / i
    return 0.0


def _recall_any(ranked_ids: list[str], gold: set[str], k: int) -> float:
    return 1.0 if gold & set(ranked_ids[:k]) else 0.0


def run_longmemeval_suite(
    _db_path: Path | None = None,
    *,
    dataset: Path | None = None,
    stratify: int | None = None,
    limit: int | None = None,
) -> BenchSuiteResult:
    """Retrieval-only LongMemEval-S footnote (skip cleanly when dataset absent)."""
    del _db_path
    path = resolve_longmemeval_path(dataset)
    if path is None:
        return BenchSuiteResult(
            suite="longmemeval",
            passed=1,
            total=1,
            cases=[
                BenchCaseResult(
                    name="skipped/no_dataset",
                    passed=True,
                    detail=_DOWNLOAD_HINT.replace("\n", " | "),
                )
            ],
        )

    questions = load_longmemeval_questions(path)
    per_type = 10 if stratify is None else max(1, stratify)
    # stratify=0 means full set
    if stratify == 0:
        sampled = questions if limit is None else questions[:limit]
    else:
        sampled = stratify_sample(questions, per_type)
        if limit is not None:
            sampled = sampled[:limit]

    set_skip_rolling_scores(True)
    r_at_5: list[float] = []
    r_at_10: list[float] = []
    mrrs: list[float] = []
    cases: list[BenchCaseResult] = []
    by_type: dict[str, list[float]] = defaultdict(list)

    try:
        for q in sampled:
            gold = set(q["gold_session_ids"])
            if not gold or not q["question"]:
                continue
            conn, _db, project = ephemeral_project_brain()
            try:
                for session in q["haystack"]:
                    ensure_fixture_neuron(
                        conn,
                        node_id=session["id"],
                        title=f"session {session['id']}",
                        content=session["content"],
                        kind="memory",
                        subtype="context",
                    )
                conn.commit()
                result = recall_live(
                    conn,
                    q["question"],
                    limit=10,
                    recall=RecallConfig(abstain_on_low_confidence=False),
                    project_dir=project,
                )
                ranked = [n.node_id for n in result.nodes]
                r5 = _recall_any(ranked, gold, 5)
                r10 = _recall_any(ranked, gold, 10)
                mrr = _mrr(ranked, gold)
                r_at_5.append(r5)
                r_at_10.append(r10)
                mrrs.append(mrr)
                by_type[str(q["type"])].append(r5)
                cases.append(
                    BenchCaseResult(
                        name=f"{q['type']}/{q['id']}",
                        passed=r5 >= 1.0,
                        detail=f"r@5={r5:.0f} r@10={r10:.0f} mrr={mrr:.3f}",
                    )
                )
            finally:
                cleanup_ephemeral_project(project, conn)
    finally:
        set_skip_rolling_scores(False)

    n = len(r_at_5) or 1
    mean_r5 = sum(r_at_5) / n if r_at_5 else 0.0
    mean_r10 = sum(r_at_10) / n if r_at_10 else 0.0
    mean_mrr = sum(mrrs) / n if mrrs else 0.0

    # Aggregate metric cases (floors are soft documentation gates, not agentmemory parity).
    cases.insert(
        0,
        BenchCaseResult(
            name="aggregate/recall_at_5",
            passed=True,
            detail=f"{mean_r5:.3f} (n={len(r_at_5)}, dataset={path.name})",
        ),
    )
    cases.insert(
        1,
        BenchCaseResult(
            name="aggregate/recall_at_10",
            passed=True,
            detail=f"{mean_r10:.3f}",
        ),
    )
    cases.insert(
        2,
        BenchCaseResult(
            name="aggregate/mrr",
            passed=True,
            detail=f"{mean_mrr:.3f}",
        ),
    )
    for qtype, vals in sorted(by_type.items()):
        rate = sum(vals) / len(vals) if vals else 0.0
        cases.append(
            BenchCaseResult(
                name=f"type/{qtype}",
                passed=True,
                detail=f"r@5={rate:.3f} n={len(vals)}",
            )
        )

    # Suite "pass" = ran successfully; per-question misses are reported but do not
    # fail the suite gate (footnote / measurement, not product regression gate).
    return BenchSuiteResult(
        suite="longmemeval",
        passed=len(cases),
        total=len(cases),
        cases=cases,
    )


def format_longmemeval_summary(result: BenchSuiteResult) -> str:
    if any(c.name == "skipped/no_dataset" for c in result.cases):
        return (
            "LongMemEval-S retrieval: SKIPPED (no dataset). "
            "Primary public claim is CMA — see docs/BENCHMARKS.md."
        )
    r5 = next((c.detail for c in result.cases if c.name == "aggregate/recall_at_5"), "?")
    r10 = next((c.detail for c in result.cases if c.name == "aggregate/recall_at_10"), "?")
    mrr = next((c.detail for c in result.cases if c.name == "aggregate/mrr"), "?")
    return (
        f"LongMemEval-S retrieval footnote: R@5={r5} R@10={r10} MRR={mrr}\n"
        "  Protocol: recall_any@K on session haystacks (FTS default). "
        "Not official LongMemEval QA accuracy."
    )
