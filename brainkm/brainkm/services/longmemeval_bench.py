"""LongMemEval-S retrieval footnote — same protocol as agentmemory (not official QA).

Downloads are optional. Without a dataset path the suite reports a single skipped PASS
so default CI stays free of the ~264MB corpus. When present, reports recall_any@K + MRR
(+ precision@K when gold sessions are sparse).

Hybrid / MiniLM mode chunks long sessions before embed+FTS so MiniLM's short context
window is not dominated by truncated role prefixes (the prior full-blob embed collapsed
R@5 to ~0.37). Rankings are aggregated back to session ids for scoring.
"""

from __future__ import annotations

import json
import random
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
from brainkm.services.ir_metrics import precision_at_k
from brainkm.services.recall import recall_live

# Cap session body so ephemeral FTS stays tractable on LongMemEval haystacks.
_MAX_SESSION_CHARS = 4000
# MiniLM / hashing embedders see ~128 tokens; chunk so embeddings are meaningful.
_CHUNK_CHARS = 480
_CHUNK_OVERLAP = 64
_DEFAULT_CACHE = Path.home() / ".cache" / "brainkm" / "longmemeval_s_cleaned.json"
_DEFAULT_STRATIFY_SEED = 42
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


def chunk_session_text(
    text: str,
    *,
    chunk_chars: int = _CHUNK_CHARS,
    overlap: int = _CHUNK_OVERLAP,
) -> list[str]:
    """Split a session blob into overlapping chunks for embed/FTS indexing."""
    cleaned = (text or "").strip()
    if not cleaned:
        return [""]
    if len(cleaned) <= chunk_chars:
        return [cleaned]
    step = max(1, chunk_chars - overlap)
    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + chunk_chars)
        piece = cleaned[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(cleaned):
            break
        start += step
    return chunks or [cleaned[:chunk_chars]]


def session_id_from_chunk_id(chunk_id: str) -> str:
    """Map ``{session}__chunk_{n}`` (or bare session id) back to the session id."""
    marker = "__chunk_"
    if marker in chunk_id:
        return chunk_id.split(marker, 1)[0]
    return chunk_id


def aggregate_ranked_to_sessions(ranked_ids: list[str]) -> list[str]:
    """Collapse chunk-level rankings to first-seen session order."""
    seen: set[str] = set()
    out: list[str] = []
    for nid in ranked_ids:
        sid = session_id_from_chunk_id(nid)
        if sid in seen:
            continue
        seen.add(sid)
        out.append(sid)
    return out


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


def stratify_sample(
    questions: list[dict],
    per_type: int,
    *,
    seed: int = _DEFAULT_STRATIFY_SEED,
) -> list[dict]:
    """Sample up to ``per_type`` questions per type with a deterministic RNG seed."""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for q in questions:
        buckets[str(q["type"])].append(q)
    rng = random.Random(seed)
    out: list[dict] = []
    for qtype in sorted(buckets):
        bucket = list(buckets[qtype])
        rng.shuffle(bucket)
        out.extend(bucket[:per_type])
    return out


def _mrr(ranked_ids: list[str], gold: set[str]) -> float:
    for i, nid in enumerate(ranked_ids, start=1):
        if nid in gold:
            return 1.0 / i
    return 0.0


def _recall_any(ranked_ids: list[str], gold: set[str], k: int) -> float:
    return 1.0 if gold & set(ranked_ids[:k]) else 0.0


def _index_haystack(
    conn,
    haystack: list[dict],
    *,
    semantic: bool,
) -> None:
    """Index sessions as overlapping chunks (better for MiniLM + FTS)."""
    from brainkm.services.semantic import embed_neuron_if_enabled

    for session in haystack:
        sid = session["id"]
        chunks = chunk_session_text(session["content"])
        for idx, chunk in enumerate(chunks):
            chunk_id = f"{sid}__chunk_{idx}"
            title = f"session {sid} chunk {idx}"
            ensure_fixture_neuron(
                conn,
                node_id=chunk_id,
                title=title,
                content=chunk,
                kind="memory",
                subtype="context",
            )
            if semantic:
                embed_neuron_if_enabled(
                    conn,
                    chunk_id,
                    title=title,
                    content=chunk,
                    semantic_enabled=True,
                )
    conn.commit()


def run_longmemeval_suite(
    _db_path: Path | None = None,
    *,
    dataset: Path | None = None,
    stratify: int | None = None,
    limit: int | None = None,
    semantic: bool = False,
    seed: int = _DEFAULT_STRATIFY_SEED,
    adapters: bool = False,
    write_ndjson: Path | None = None,
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
        sampled = stratify_sample(questions, per_type, seed=seed)
        if limit is not None:
            sampled = sampled[:limit]

    from brainkm.models.brain_config import SemanticConfig

    # fts_primary: vector re-ranks FTS hits only — equal RRF previously collapsed
    # LongMemEval haystacks (~0.37 R@5) by promoting non-lexical vector noise.
    semantic_cfg = (
        SemanticConfig(enabled=True, rrf_k=30, fusion_mode="fts_primary")
        if semantic
        else SemanticConfig(enabled=False)
    )

    set_skip_rolling_scores(True)
    r_at_5: list[float] = []
    r_at_10: list[float] = []
    p_at_5: list[float] = []
    mrrs: list[float] = []
    cases: list[BenchCaseResult] = []
    by_type: dict[str, list[float]] = defaultdict(list)
    adapter_rows: list[dict[str, object]] = []

    try:
        for q in sampled:
            gold = set(q["gold_session_ids"])
            if not gold or not q["question"]:
                continue
            conn, _db, project = ephemeral_project_brain()
            try:
                _index_haystack(conn, q["haystack"], semantic=semantic)
                result = recall_live(
                    conn,
                    q["question"],
                    limit=20,
                    recall=RecallConfig(abstain_on_low_confidence=False),
                    semantic=semantic_cfg,
                    project_dir=project,
                )
                ranked = aggregate_ranked_to_sessions([n.node_id for n in result.nodes])
                r5 = _recall_any(ranked, gold, 5)
                r10 = _recall_any(ranked, gold, 10)
                p5 = precision_at_k(ranked, gold, 5)
                mrr = _mrr(ranked, gold)
                r_at_5.append(r5)
                r_at_10.append(r10)
                p_at_5.append(p5)
                mrrs.append(mrr)
                by_type[str(q["type"])].append(r5)
                cases.append(
                    BenchCaseResult(
                        name=f"{q['type']}/{q['id']}",
                        passed=r5 >= 1.0,
                        detail=(
                            f"r@5={r5:.0f} r@10={r10:.0f} p@5={p5:.3f} mrr={mrr:.3f}"
                        ),
                    )
                )
                if adapters:
                    from brainkm.services.bench_adapters import (
                        naive_title_scan_rank,
                        score_ranked_sessions,
                    )

                    titles = {
                        s["id"]: f"session {s['id']}" for s in q["haystack"]
                    }
                    contents = {s["id"]: s["content"] for s in q["haystack"]}
                    naive = aggregate_ranked_to_sessions(
                        naive_title_scan_rank(q["question"], titles, contents, limit=10)
                    )
                    # FTS-only arm on the same chunked index
                    fts_result = recall_live(
                        conn,
                        q["question"],
                        limit=20,
                        recall=RecallConfig(abstain_on_low_confidence=False),
                        semantic=SemanticConfig(enabled=False),
                        project_dir=project,
                    )
                    fts_ranked = aggregate_ranked_to_sessions(
                        [n.node_id for n in fts_result.nodes]
                    )
                    adapter_rows.append(
                        {
                            "id": q["id"],
                            "type": q["type"],
                            "brainkm": score_ranked_sessions(ranked, gold),
                            "bm25": score_ranked_sessions(fts_ranked, gold),
                            "naive": score_ranked_sessions(naive, gold),
                        }
                    )
            finally:
                cleanup_ephemeral_project(project, conn)
    finally:
        set_skip_rolling_scores(False)

    n = len(r_at_5) or 1
    mean_r5 = sum(r_at_5) / n if r_at_5 else 0.0
    mean_r10 = sum(r_at_10) / n if r_at_10 else 0.0
    mean_p5 = sum(p_at_5) / n if p_at_5 else 0.0
    mean_mrr = sum(mrrs) / n if mrrs else 0.0
    mode = "semantic-chunked" if semantic else "fts-chunked"

    cases.insert(
        0,
        BenchCaseResult(
            name="aggregate/recall_at_5",
            passed=True,
            detail=f"{mean_r5:.3f} (n={len(r_at_5)}, dataset={path.name}, mode={mode})",
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
            name="aggregate/precision_at_5",
            passed=True,
            detail=f"{mean_p5:.3f}",
        ),
    )
    cases.insert(
        3,
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

    if adapters and adapter_rows:
        cases.extend(_adapter_aggregate_cases(adapter_rows))
        if write_ndjson is not None:
            from brainkm.services.bench_adapters import write_ndjson as _write_ndjson

            _write_ndjson(write_ndjson, adapter_rows)

    return BenchSuiteResult(
        suite="longmemeval",
        passed=len(cases),
        total=len(cases),
        cases=cases,
    )


def _adapter_aggregate_cases(rows: list[dict[str, object]]) -> list[BenchCaseResult]:
    arms = ("brainkm", "bm25", "naive")
    out: list[BenchCaseResult] = []
    for arm in arms:
        r5 = [float(row[arm]["r@5"]) for row in rows]  # type: ignore[index]
        p5 = [float(row[arm]["p@5"]) for row in rows]  # type: ignore[index]
        mrr = [float(row[arm]["mrr"]) for row in rows]  # type: ignore[index]
        n = len(r5) or 1
        out.append(
            BenchCaseResult(
                name=f"adapter/{arm}",
                passed=True,
                detail=(
                    f"r@5={sum(r5)/n:.3f} p@5={sum(p5)/n:.3f} "
                    f"mrr={sum(mrr)/n:.3f} n={len(r5)}"
                ),
            )
        )
    return out


def format_longmemeval_summary(result: BenchSuiteResult) -> str:
    if any(c.name == "skipped/no_dataset" for c in result.cases):
        return (
            "LongMemEval-S retrieval: SKIPPED (no dataset). "
            "See docs/BENCHMARKS.md for published footnote + CMA diagnostics."
        )
    r5 = next((c.detail for c in result.cases if c.name == "aggregate/recall_at_5"), "?")
    r10 = next((c.detail for c in result.cases if c.name == "aggregate/recall_at_10"), "?")
    p5 = next(
        (c.detail for c in result.cases if c.name == "aggregate/precision_at_5"), "?"
    )
    mrr = next((c.detail for c in result.cases if c.name == "aggregate/mrr"), "?")
    adapter_lines = [
        f"  {c.name}: {c.detail}"
        for c in result.cases
        if c.name.startswith("adapter/")
    ]
    extra = ("\n" + "\n".join(adapter_lines)) if adapter_lines else ""
    return (
        f"LongMemEval-S retrieval footnote: R@5={r5} R@10={r10} P@5={p5} MRR={mrr}\n"
        "  Protocol: recall_any@K on chunked session haystacks "
        "(FTS default; --semantic for MiniLM hybrid). "
        "Not official LongMemEval QA accuracy."
        f"{extra}"
    )
