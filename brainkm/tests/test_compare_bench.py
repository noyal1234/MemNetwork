"""Tests for with-brain vs without-brain compare suite."""

from __future__ import annotations

from pathlib import Path

from brainkm.bench.results import BenchCaseResult, BenchSuiteResult
from brainkm.db.connection import connect
from brainkm.db.migrate import migrate
from brainkm.models.brain_config import BrainConfig
from brainkm.services.bench_runner import format_suite_result, run_bench_suite
from brainkm.services.compare_bench import (
    CompareFixture,
    CompareScenario,
    evaluate_compare_scenario,
    format_compare_summary,
    load_package_compare_fixture,
)
from tests.conftest import insert_node


def test_load_compare_fixture_has_memnetwork_scenarios() -> None:
    fixture = load_package_compare_fixture()
    assert fixture.id == "compare_v1"
    assert len(fixture.scenarios) == 4
    ids = {s.id for s in fixture.scenarios}
    assert ids == {"token_budget", "mcp_dispatch", "graphify_routing", "session_snapshot"}
    assert all(s.baseline_files for s in fixture.scenarios)
    assert "JWT" not in " ".join(s.query for s in fixture.scenarios)


def test_evaluate_compare_with_vs_without_savings(tmp_path: Path) -> None:
    """Native file dump is large; live pack stays under budget and smaller."""
    project_dir = tmp_path
    db_path = project_dir / ".brain" / "brain.db"
    migrate(db_path=db_path, run_integrity_check=False)

    baseline = project_dir / "services" / "budget.py"
    baseline.parent.mkdir(parents=True)
    # ~2k+ tokens of naive read without brainkm
    baseline.write_text(("token budget greedy_truncate pad\n" * 400), encoding="utf-8")

    conn = connect(db_path)
    try:
        insert_node(
            conn,
            node_id="cmp-budget",
            subtype="decision",
            title="Token budget policy",
            content="greedy_truncate keeps highest-priority neurons under total_tokens cap",
        )
        conn.commit()
        scenario = CompareScenario(
            id="token_budget",
            query="how does token budget greedy truncation work",
            baseline_files=["services/budget.py"],
            must_include_substrings=("greedy_truncate", "total_tokens"),
        )
        outcome = evaluate_compare_scenario(
            conn,
            scenario,
            project_dir=project_dir,
            config=BrainConfig(),
        )
    finally:
        conn.close()

    assert outcome.passed is True
    assert "without=" in outcome.detail
    assert "with=" in outcome.detail
    assert "reduction=" in outcome.detail
    assert "facts=2/2" in outcome.detail


def test_compare_empty_pack_skips_fact_check(tmp_path: Path) -> None:
    project_dir = tmp_path
    db_path = project_dir / ".brain" / "brain.db"
    migrate(db_path=db_path, run_integrity_check=False)

    baseline = project_dir / "big.py"
    baseline.write_text("word " * 2000, encoding="utf-8")

    conn = connect(db_path)
    try:
        # No relevant neurons — pack may be empty; substrings must not hard-fail.
        scenario = CompareScenario(
            id="empty",
            query="zzzznonexistenttopic999",
            baseline_files=["big.py"],
            must_include_substrings=("must_not_appear",),
        )
        outcome = evaluate_compare_scenario(
            conn,
            scenario,
            project_dir=project_dir,
            config=BrainConfig(),
        )
    finally:
        conn.close()

    assert "facts=skipped_empty_pack" in outcome.detail or outcome.passed is True


def test_run_compare_suite_via_runner(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path
    db_path = project_dir / ".brain" / "brain.db"
    migrate(db_path=db_path, run_integrity_check=False)

    baseline = project_dir / "hooks.py"
    baseline.write_text(("SessionStart frozen snapshot injection\n" * 300), encoding="utf-8")

    conn = connect(db_path)
    try:
        insert_node(
            conn,
            node_id="cmp-snap",
            subtype="decision",
            title="Frozen injection snapshot",
            content="SessionStart builds frozen snapshot; mid-session remember does not mutate",
        )
        conn.commit()
    finally:
        conn.close()

    mini = CompareFixture(
        version=1,
        id="compare_test",
        scenarios=[
            CompareScenario(
                id="session_snapshot",
                query="SessionStart frozen injection snapshot",
                baseline_files=["hooks.py"],
                must_include_substrings=("SessionStart", "snapshot"),
            )
        ],
    )
    monkeypatch.setattr(
        "brainkm.services.compare_bench.load_package_compare_fixture",
        lambda: mini,
    )

    result = run_bench_suite("compare", db_path)
    assert result.suite == "compare"
    assert result.total == 1
    assert result.passed == 1
    text = format_suite_result(result)
    assert "without=" in text
    assert "Compare (token proxy)" in text


def test_format_compare_summary() -> None:
    result = BenchSuiteResult(
        suite="compare",
        passed=2,
        total=2,
        cases=[
            BenchCaseResult(
                name="a",
                passed=True,
                detail="without=5000 with=400/1500 reduction=92% savings=12.5x facts=2/2",
            ),
            BenchCaseResult(
                name="b",
                passed=True,
                detail="without=3000 with=500/1500 reduction=83% savings=6.0x facts=1/1",
            ),
        ],
    )
    summary = format_compare_summary(result)
    assert "Average with-vs-without reduction" in summary
    assert "fewer tokens with brain" in summary


def test_run_compare_suite_rejects_unknown_via_runner(brain_db: Path) -> None:
    import pytest

    with pytest.raises(ValueError, match="unknown bench suite"):
        run_bench_suite("not-a-suite", brain_db)
