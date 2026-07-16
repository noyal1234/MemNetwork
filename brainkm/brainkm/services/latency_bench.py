"""Latency bench — smoke vs loaded profiles with cold/warm variance."""

from __future__ import annotations

import statistics
import time
from pathlib import Path

from brainkm.bench.results import BenchCaseResult, BenchSuiteResult
from brainkm.config import set_skip_rolling_scores
from brainkm.db.connection import connect
from brainkm.models.brain_config import BrainConfig
from brainkm.services.bench_db import (
    cleanup_ephemeral_project,
    ensure_fixture_neuron,
    ephemeral_project_brain,
)
from brainkm.services.context_pack import compile_context_pack
from brainkm.services.recall import recall_live

# Smoke targets (tiny ephemeral brain) — without optional ONNX reranker.
SMOKE_P50_RECALL_MS = 80.0
SMOKE_P95_RECALL_MS = 150.0
SMOKE_P95_CONTEXT_PACK_MS = 250.0

# Loaded targets (populated project brain) — calibrated for ~1k+ code nodes.
LOADED_P50_RECALL_MS = 800.0
LOADED_P95_RECALL_MS = 1200.0
LOADED_P95_CONTEXT_PACK_MS = 1500.0

# Back-compat aliases used by older tests/docs.
P50_RECALL_MS = SMOKE_P50_RECALL_MS
P95_RECALL_MS = SMOKE_P95_RECALL_MS
P95_CONTEXT_PACK_MS = SMOKE_P95_CONTEXT_PACK_MS

DEFAULT_QUERIES = (
    "why did we choose JWT",
    "what calls context_pack",
    "auth token refresh error",
    "graphify auto sync",
    "budget total_tokens default",
)

DEFAULT_WARM_REPEATS = 10


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


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return float(statistics.stdev(values))


def _measure_profile(
    conn,
    *,
    project_dir: Path,
    config: BrainConfig,
    queries: tuple[str, ...] = DEFAULT_QUERIES,
    warm_repeats: int = DEFAULT_WARM_REPEATS,
) -> dict[str, float]:
    """Return cold + warm latency stats for recall and context_pack."""
    cold_recall: list[float] = []
    cold_pack: list[float] = []
    warm_recall: list[float] = []
    warm_pack: list[float] = []

    for query in queries:
        cold_recall.append(
            _time_ms(lambda q=query: recall_live(conn, q, config=config, project_dir=project_dir))
        )
        cold_pack.append(
            _time_ms(
                lambda q=query: compile_context_pack(
                    conn, q, config=config, project_dir=project_dir
                )
            )
        )
        for _ in range(warm_repeats):
            warm_recall.append(
                _time_ms(
                    lambda q=query: recall_live(conn, q, config=config, project_dir=project_dir)
                )
            )
            warm_pack.append(
                _time_ms(
                    lambda q=query: compile_context_pack(
                        conn, q, config=config, project_dir=project_dir
                    )
                )
            )

    return {
        "cold_recall_mean": float(statistics.fmean(cold_recall)) if cold_recall else 0.0,
        "cold_pack_mean": float(statistics.fmean(cold_pack)) if cold_pack else 0.0,
        "recall_p50": _percentile(warm_recall, 50),
        "recall_p95": _percentile(warm_recall, 95),
        "recall_mean": float(statistics.fmean(warm_recall)) if warm_recall else 0.0,
        "recall_stdev": _stdev(warm_recall),
        "pack_p50": _percentile(warm_pack, 50),
        "pack_p95": _percentile(warm_pack, 95),
        "pack_mean": float(statistics.fmean(warm_pack)) if warm_pack else 0.0,
        "pack_stdev": _stdev(warm_pack),
        "warm_n": float(len(warm_recall)),
    }


def _cases_for_stats(
    stats: dict[str, float],
    *,
    profile: str,
    p50_recall: float,
    p95_recall: float,
    p95_pack: float,
) -> list[BenchCaseResult]:
    prefix = profile
    return [
        BenchCaseResult(
            name=f"{prefix}_recall_p50",
            passed=stats["recall_p50"] <= p50_recall,
            detail=(
                f"{stats['recall_p50']:.1f}ms (target <={p50_recall:.0f}; "
                f"mean={stats['recall_mean']:.1f}±{stats['recall_stdev']:.1f}; "
                f"cold_mean={stats['cold_recall_mean']:.1f})"
            ),
        ),
        BenchCaseResult(
            name=f"{prefix}_recall_p95",
            passed=stats["recall_p95"] <= p95_recall,
            detail=f"{stats['recall_p95']:.1f}ms (target <={p95_recall:.0f})",
        ),
        BenchCaseResult(
            name=f"{prefix}_context_pack_p50",
            passed=stats["pack_p50"] <= p50_recall * 1.5,
            detail=(
                f"{stats['pack_p50']:.1f}ms "
                f"(mean={stats['pack_mean']:.1f}±{stats['pack_stdev']:.1f}; "
                f"cold_mean={stats['cold_pack_mean']:.1f})"
            ),
        ),
        BenchCaseResult(
            name=f"{prefix}_context_pack_p95",
            passed=stats["pack_p95"] <= p95_pack,
            detail=f"{stats['pack_p95']:.1f}ms (target <={p95_pack:.0f})",
        ),
        BenchCaseResult(
            name=f"{prefix}_warm_samples",
            passed=stats["warm_n"] >= 10,
            detail=f"n={int(stats['warm_n'])} warm timings",
        ),
    ]


def run_latency_smoke() -> BenchSuiteResult:
    """Tiny ephemeral brain — tight SLOs."""
    set_skip_rolling_scores(True)
    conn, _db, project_dir = ephemeral_project_brain()
    try:
        ensure_fixture_neuron(
            conn,
            node_id="lat_smoke_budget",
            title="Token budget",
            content="budget total_tokens default 1500 greedy_truncate",
            subtype="fact",
        )
        ensure_fixture_neuron(
            conn,
            node_id="lat_smoke_graph",
            title="Graphify auto sync",
            content="graphify auto sync after write edit",
            subtype="fact",
        )
        conn.commit()
        config = BrainConfig()
        stats = _measure_profile(
            conn,
            project_dir=project_dir,
            config=config,
            warm_repeats=DEFAULT_WARM_REPEATS,
        )
    finally:
        cleanup_ephemeral_project(project_dir, conn)
        set_skip_rolling_scores(False)

    cases = _cases_for_stats(
        stats,
        profile="smoke",
        p50_recall=SMOKE_P50_RECALL_MS,
        p95_recall=SMOKE_P95_RECALL_MS,
        p95_pack=SMOKE_P95_CONTEXT_PACK_MS,
    )
    passed = sum(1 for case in cases if case.passed)
    return BenchSuiteResult(suite="latency-smoke", passed=passed, total=len(cases), cases=cases)


def run_latency_loaded(db_path: Path) -> BenchSuiteResult:
    """Populated project brain — corpus-scaled SLOs."""
    config = BrainConfig()
    project_dir = db_path.parent.parent
    set_skip_rolling_scores(True)
    conn = connect(db_path)
    try:
        stats = _measure_profile(
            conn,
            project_dir=project_dir,
            config=config,
            warm_repeats=DEFAULT_WARM_REPEATS,
        )
    finally:
        conn.close()
        set_skip_rolling_scores(False)

    cases = _cases_for_stats(
        stats,
        profile="loaded",
        p50_recall=LOADED_P50_RECALL_MS,
        p95_recall=LOADED_P95_RECALL_MS,
        p95_pack=LOADED_P95_CONTEXT_PACK_MS,
    )
    passed = sum(1 for case in cases if case.passed)
    return BenchSuiteResult(suite="latency-loaded", passed=passed, total=len(cases), cases=cases)


def run_latency_suite(
    db_path: Path,
    *,
    profile: str = "loaded",
) -> BenchSuiteResult:
    """Measure latency for ``smoke``, ``loaded``, or ``both`` profiles."""
    profile = profile.lower().strip()
    if profile == "smoke":
        return run_latency_smoke()
    if profile == "loaded":
        return run_latency_loaded(db_path)
    if profile == "both":
        smoke = run_latency_smoke()
        loaded = run_latency_loaded(db_path)
        cases = list(smoke.cases) + list(loaded.cases)
        passed = sum(1 for case in cases if case.passed)
        return BenchSuiteResult(suite="latency", passed=passed, total=len(cases), cases=cases)
    msg = f"unknown latency profile: {profile} (use smoke|loaded|both)"
    raise ValueError(msg)
