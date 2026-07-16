"""Tests for retrieval ranking bench."""

from __future__ import annotations

from brainkm.services.bench_runner import run_bench_suite
from brainkm.services.retrieval_bench import load_package_retrieval_fixture


def test_retrieval_fixture_scale() -> None:
    fixture = load_package_retrieval_fixture()
    assert fixture.id == "retrieval_v1"
    assert len(fixture.queries) >= 60
    assert len(fixture.corpus) >= 30
    assert sum(1 for q in fixture.queries if q.should_abstain) >= 4
    assert sum(1 for q in fixture.queries if q.expect_noise_only) >= 4


def test_retrieval_suite_meets_floors(tmp_path) -> None:
    db_path = tmp_path / ".brain" / "brain.db"
    db_path.parent.mkdir(parents=True)
    result = run_bench_suite("retrieval", db_path)
    assert result.suite == "retrieval"
    assert result.total >= 6
    # Product-grade floors — may not be 100%, but suite should clear configured floors.
    assert result.pass_rate >= 0.8, format_cases(result)


def format_cases(result) -> str:
    return "\n".join(f"{c.name}: {c.passed} {c.detail}" for c in result.cases)
