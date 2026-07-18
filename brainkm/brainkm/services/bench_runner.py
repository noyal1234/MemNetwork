"""Bench suite runner — product-grade eval + regression canaries."""

from __future__ import annotations

from pathlib import Path

from brainkm.bench.results import BenchCaseResult, BenchSuiteResult
from brainkm.models.brain_config import RecallConfig
from brainkm.services.abstention_calibrate import calibrate_abstention, load_package_fixture
from brainkm.services.compare_bench import format_compare_summary, run_compare_suite
from brainkm.services.recall import recall_live
from brainkm.services.retrieval_bench import run_retrieval_suite
from brainkm.services.task_bench import format_task_summary, run_task_suite
from brainkm.services.token_bench import format_token_summary, run_budget_suite, run_token_suite

CANARY_SUITES = (
    "abstention",
    "dmr",
    "longmem",
    "budget",
    "compaction",
)

EVAL_CORE_SUITES = (
    "retrieval",
    "task",
)


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

    return run_latency_suite(db_path, profile="both")


SUITE_RUNNERS = {
    "abstention": run_abstention_suite,
    "token": run_token_suite,
    "dmr": run_dmr_suite,
    "longmem": run_longmem_suite,
    "budget": run_budget_suite,
    "compaction": run_compaction_suite,
    "latency": run_latency_suite_entry,
    "compare": run_compare_suite,
    "retrieval": run_retrieval_suite,
    "task": lambda db_path: run_task_suite(db_path, fixture_only=False, judge=False),
    "scorecard": lambda _db: __import__(
        "brainkm.services.scorecard_bench", fromlist=["run_scorecard_suite"]
    ).run_scorecard_suite(_db),
    "cma": lambda _db: __import__(
        "brainkm.services.cma_bench", fromlist=["run_cma_suite"]
    ).run_cma_suite(_db),
    "longmemeval": lambda _db: __import__(
        "brainkm.services.longmemeval_bench", fromlist=["run_longmemeval_suite"]
    ).run_longmemeval_suite(_db),
}


def run_bench_suite(
    suite: str,
    db_path: Path,
    *,
    live: bool = False,
    profile: str = "both",
    fixture_only: bool = False,
    judge: bool = False,
) -> BenchSuiteResult:
    if suite == "token" and live:
        return run_token_suite(db_path, live=True)
    if suite == "latency":
        from brainkm.services.latency_bench import run_latency_suite

        return run_latency_suite(db_path, profile=profile)
    if suite == "task":
        return run_task_suite(db_path, fixture_only=fixture_only, judge=judge)
    if suite == "eval":
        return run_eval_suite(
            db_path,
            profile=profile,
            fixture_only=fixture_only,
            judge=judge,
        )
    runner = SUITE_RUNNERS.get(suite)
    if runner is None:
        msg = f"unknown bench suite: {suite}"
        raise ValueError(msg)
    return runner(db_path)


def run_eval_suite(
    db_path: Path,
    *,
    profile: str = "both",
    fixture_only: bool = False,
    judge: bool = False,
) -> BenchSuiteResult:
    """Product-grade eval: retrieval + task + latency + regression canaries."""
    from brainkm.services.latency_bench import run_latency_suite

    cases: list[BenchCaseResult] = []
    blocks: list[BenchSuiteResult] = [
        run_retrieval_suite(db_path),
        run_task_suite(db_path, fixture_only=fixture_only, judge=judge),
        run_latency_suite(db_path, profile=profile),
    ]
    for name in CANARY_SUITES:
        blocks.append(SUITE_RUNNERS[name](db_path))

    for block in blocks:
        block_pass = block.passed == block.total
        cases.append(
            BenchCaseResult(
                name=block.suite,
                passed=block_pass,
                detail=f"{block.passed}/{block.total} ({block.pass_rate:.0%})",
            )
        )
        for case in block.cases:
            cases.append(
                BenchCaseResult(
                    name=f"{block.suite}/{case.name}",
                    passed=case.passed,
                    detail=case.detail,
                )
            )

    # Hard gate: core suites must fully pass; canaries reported but eval pass =
    # all core metric cases under retrieval/task/latency that are direct children.
    core_ok = all(
        case.passed
        for case in cases
        if case.name in {"retrieval", "task", "latency", "latency-smoke", "latency-loaded"}
        or case.name.startswith("retrieval/")
        or case.name.startswith("task/")
        or case.name.startswith("latency")
    )
    # Simpler: eval suite passes iff every case passed (canaries included as gate too).
    passed = sum(1 for case in cases if case.passed)
    _ = core_ok  # documented intent; full gate includes canaries for release script
    return BenchSuiteResult(suite="eval", passed=passed, total=len(cases), cases=cases)


def format_suite_result(result: BenchSuiteResult) -> str:
    if result.suite == "scorecard":
        from brainkm.services.scorecard_bench import format_scorecard_summary

        return format_scorecard_summary(result)
    if result.suite == "cma":
        from brainkm.services.cma_bench import format_cma_summary

        lines = [f"Suite {result.suite}: {result.passed}/{result.total} ({result.pass_rate:.0%})"]
        for case in result.cases:
            status = "PASS" if case.passed else "FAIL"
            lines.append(f"  [{status}] {case.name}: {case.detail}")
        lines.append(format_cma_summary(result))
        lines.append(
            "CMA = Common Memory Axes (coding-agent corpus). "
            "Not a LongMemEval-S leaderboard claim — see docs/BENCHMARKS.md."
        )
        return "\n".join(lines)
    if result.suite == "longmemeval":
        from brainkm.services.longmemeval_bench import format_longmemeval_summary

        lines = [f"Suite {result.suite}: {result.passed}/{result.total} ({result.pass_rate:.0%})"]
        for case in result.cases:
            status = "PASS" if case.passed else "FAIL"
            lines.append(f"  [{status}] {case.name}: {case.detail}")
        lines.append(format_longmemeval_summary(result))
        return "\n".join(lines)
    lines = [f"Suite {result.suite}: {result.passed}/{result.total} ({result.pass_rate:.0%})"]
    for case in result.cases:
        status = "PASS" if case.passed else "FAIL"
        lines.append(f"  [{status}] {case.name}: {case.detail}")
    summary = format_token_summary(result)
    if summary:
        lines.append(summary)
    compare_summary = format_compare_summary(result)
    if compare_summary:
        lines.append(compare_summary)
    task_summary = format_task_summary(result)
    if task_summary:
        lines.append(task_summary)
    if result.suite == "token-live":
        lines.append(
            "Live mode: uses project brain.db (graph + neurons). "
            "Cap pass = pack <= budget.total_tokens."
        )
    if result.suite == "compare":
        lines.append(
            "Compare (token proxy): without=naive multi-file read; "
            "with=live context_pack. Prefer `task` for success metrics."
        )
    if result.suite == "task":
        lines.append(
            "Task: without=selective token-capped reads; with=context_pack; "
            "gold checklist is the hard gate."
        )
    if result.suite == "retrieval":
        lines.append("Retrieval: held-out gold corpus; metrics are means over ranking queries.")
    if result.suite == "eval":
        lines.append(
            "Eval aggregates retrieval + task + latency + canaries. "
            "Headline quality = retrieval/task, not canary 100% rates."
        )
    return "\n".join(lines)
