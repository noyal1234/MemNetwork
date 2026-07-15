"""Bench suite runner — token, DMR-lite, LongMemEval-lite, budget, compaction."""

from __future__ import annotations

from pathlib import Path

from brainkm.bench.results import BenchCaseResult, BenchSuiteResult
from brainkm.models.brain_config import RecallConfig
from brainkm.services.abstention_calibrate import calibrate_abstention, load_package_fixture
from brainkm.services.recall import recall_live
from brainkm.services.token_bench import format_token_summary, run_budget_suite, run_token_suite


def run_abstention_suite(db_path: Path) -> BenchSuiteResult:
    """Calibrate + score abstention on an isolated fixture corpus.

    Calibration artifacts are written into the *project* next to ``db_path``
    (``.brain/abstention_calibration.json``), but fixture neurons are never
    inserted into the live project brain — that polluted FTS scores and made
    percentile search fail on real corpora.
    """
    from brainkm.config import set_skip_rolling_scores
    from brainkm.services.bench_db import cleanup_ephemeral_project, ephemeral_project_brain

    project_dir = db_path.parent.parent
    fixture = load_package_fixture()
    set_skip_rolling_scores(True)
    conn, _ephemeral_db, ephemeral_project = ephemeral_project_brain()
    try:
        calibration = calibrate_abstention(conn, RecallConfig(), fixture, seed_corpus=True)
        conn.commit()
        from brainkm.services.abstention_calibrate import save_calibration

        save_calibration(calibration, project_dir)
        cases: list[BenchCaseResult] = []
        # Score fixture queries on the same isolated corpus used for calibration.
        for item in fixture.queries:
            result = recall_live(
                conn,
                item.query,
                recall=RecallConfig(),
                project_dir=project_dir,
            )
            recalled = not result.abstained and len(result.nodes) > 0
            passed = recalled == item.should_recall
            cases.append(
                BenchCaseResult(
                    name=item.query[:40],
                    passed=passed,
                    detail=f"abstained={result.abstained} hits={len(result.nodes)}",
                )
            )
    finally:
        cleanup_ephemeral_project(ephemeral_project, conn)
        set_skip_rolling_scores(False)
    passed = sum(1 for case in cases if case.passed)
    return BenchSuiteResult(suite="abstention", passed=passed, total=len(cases), cases=cases)


def run_dmr_suite(_db_path: Path) -> BenchSuiteResult:
    from brainkm.services.dmr_bench import run_dmr_suite as run_real_dmr_suite

    return run_real_dmr_suite(_db_path)


def run_longmem_suite(_db_path: Path) -> BenchSuiteResult:
    from brainkm.services.longmem_bench import run_longmem_suite as run_real_longmem_suite

    return run_real_longmem_suite(_db_path)


def run_compaction_suite(_db_path: Path) -> BenchSuiteResult:
    from brainkm.services.compaction_bench import run_compaction_suite as run_real_compaction_suite

    return run_real_compaction_suite(_db_path)


def run_latency_suite_entry(db_path: Path) -> BenchSuiteResult:
    from brainkm.services.latency_bench import run_latency_suite

    return run_latency_suite(db_path)


SUITE_RUNNERS = {
    "abstention": run_abstention_suite,
    "token": run_token_suite,
    "dmr": run_dmr_suite,
    "longmem": run_longmem_suite,
    "budget": run_budget_suite,
    "compaction": run_compaction_suite,
    "latency": run_latency_suite_entry,
}


def run_bench_suite(suite: str, db_path: Path, *, live: bool = False) -> BenchSuiteResult:
    if suite == "token" and live:
        return run_token_suite(db_path, live=True)
    runner = SUITE_RUNNERS.get(suite)
    if runner is None:
        msg = f"unknown bench suite: {suite}"
        raise ValueError(msg)
    return runner(db_path)


def format_suite_result(result: BenchSuiteResult) -> str:
    lines = [f"Suite {result.suite}: {result.passed}/{result.total} ({result.pass_rate:.0%})"]
    for case in result.cases:
        status = "PASS" if case.passed else "FAIL"
        lines.append(f"  [{status}] {case.name}: {case.detail}")
    summary = format_token_summary(result)
    if summary:
        lines.append(summary)
    if result.suite == "token-live":
        lines.append("Live mode: uses project brain.db (graph + neurons). Cap pass = pack <= budget.total_tokens.")
    return "\n".join(lines)
