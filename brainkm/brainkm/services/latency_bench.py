"""Latency bench suite — p50/p95 for recall and context_pack."""

from __future__ import annotations

import statistics
import time
from pathlib import Path

from brainkm.bench.results import BenchCaseResult, BenchSuiteResult
from brainkm.db.connection import connect
from brainkm.models.brain_config import BrainConfig
from brainkm.services.context_pack import compile_context_pack
from brainkm.services.recall import recall_live

# Default targets (ms) — without optional ONNX reranker.
P95_RECALL_MS = 150.0
P95_CONTEXT_PACK_MS = 250.0
P50_RECALL_MS = 80.0


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    k = (len(ordered) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(ordered) - 1)
    if f == c:
        return ordered[f]
    return ordered[f] + (ordered[c] - ordered[f]) * (k - f)


def _time_ms(fn) -> float:  # noqa: ANN001
    start = time.perf_counter()
    fn()
    return (time.perf_counter() - start) * 1000.0


DEFAULT_QUERIES = (
    "why did we choose JWT",
    "what calls context_pack",
    "auth token refresh error",
    "graphify auto sync",
    "budget total_tokens default",
)


def run_latency_suite(db_path: Path) -> BenchSuiteResult:
    """Measure recall/context_pack latency against the given brain.db."""
    config = BrainConfig()
    project_dir = db_path.parent.parent
    recall_samples: list[float] = []
    pack_samples: list[float] = []

    conn = connect(db_path)
    try:
        # Warmup
        recall_live(conn, DEFAULT_QUERIES[0], config=config, project_dir=project_dir)
        for query in DEFAULT_QUERIES:
            for _ in range(3):
                recall_samples.append(
                    _time_ms(
                        lambda q=query: recall_live(
                            conn, q, config=config, project_dir=project_dir
                        )
                    )
                )
                pack_samples.append(
                    _time_ms(
                        lambda q=query: compile_context_pack(
                            conn, q, config=config, project_dir=project_dir
                        )
                    )
                )
    finally:
        conn.close()

    recall_p50 = _percentile(recall_samples, 50)
    recall_p95 = _percentile(recall_samples, 95)
    pack_p50 = _percentile(pack_samples, 50)
    pack_p95 = _percentile(pack_samples, 95)

    cases = [
        BenchCaseResult(
            name="recall_p50",
            passed=recall_p50 <= P50_RECALL_MS,
            detail=f"{recall_p50:.1f}ms (target <={P50_RECALL_MS})",
        ),
        BenchCaseResult(
            name="recall_p95",
            passed=recall_p95 <= P95_RECALL_MS,
            detail=f"{recall_p95:.1f}ms (target <={P95_RECALL_MS})",
        ),
        BenchCaseResult(
            name="context_pack_p50",
            passed=pack_p50 <= P50_RECALL_MS * 1.5,
            detail=f"{pack_p50:.1f}ms",
        ),
        BenchCaseResult(
            name="context_pack_p95",
            passed=pack_p95 <= P95_CONTEXT_PACK_MS,
            detail=f"{pack_p95:.1f}ms (target <={P95_CONTEXT_PACK_MS})",
        ),
        BenchCaseResult(
            name="mean_recall",
            passed=True,
            detail=f"{statistics.fmean(recall_samples):.1f}ms over {len(recall_samples)} runs",
        ),
    ]
    passed = sum(1 for case in cases if case.passed)
    return BenchSuiteResult(suite="latency", passed=passed, total=len(cases), cases=cases)
