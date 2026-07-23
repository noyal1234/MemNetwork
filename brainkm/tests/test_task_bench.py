"""Tests for task-success bench."""

from __future__ import annotations

from pathlib import Path

import pytest

from brainkm.services.bench_runner import run_bench_suite
from brainkm.services.task_bench import (
    SelectiveSlice,
    gold_coverage,
    load_package_task_fixture,
    measure_selective_baseline,
    run_task_suite,
)


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_task_fixture_scale() -> None:
    fixture = load_package_task_fixture()
    assert fixture.id == "task_v1"
    assert len(fixture.scenarios) >= 20
    assert all(s.selective_baseline for s in fixture.scenarios)
    assert all(s.answer_facts for s in fixture.scenarios)


def test_selective_baseline_is_capped(repo_root: Path) -> None:
    slices = (SelectiveSlice(path="brainkm/brainkm/services/budget.py", max_tokens=100),)
    text, tokens = measure_selective_baseline(repo_root, slices)
    assert text
    assert tokens <= 100


def test_gold_coverage() -> None:
    assert (
        gold_coverage("greedy_truncate under total_tokens", ("greedy_truncate", "total_tokens"))
        == 1.0
    )
    assert gold_coverage("only greedy_truncate here", ("greedy_truncate", "total_tokens")) == 0.5


def test_task_suite_fixture_only(repo_root: Path) -> None:
    # db_path under repo so selective baselines resolve; suite uses ephemeral seeds.
    db_path = repo_root / ".brain" / "brain.db"
    result = run_task_suite(db_path, fixture_only=True, judge=False)
    assert result.suite == "task"
    assert result.total >= 20
    assert result.pass_rate >= 0.65, "\n".join(f"{c.name}: {c.detail}" for c in result.cases)


def test_task_judge_skips_without_ollama(repo_root: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "brainkm.services.task_bench._ollama_chat",
        lambda *a, **k: None,
    )
    db_path = repo_root / ".brain" / "brain.db"
    result = run_task_suite(db_path, fixture_only=True, judge=True)
    assert any("judge=skipped" in c.detail for c in result.cases)


def test_run_bench_suite_task(repo_root: Path) -> None:
    result = run_bench_suite("task", repo_root / ".brain" / "brain.db", fixture_only=True)
    assert result.suite == "task"
    assert result.total >= 20
    assert result.pass_rate >= 0.65, "\n".join(f"{c.name}: {c.detail}" for c in result.cases)
