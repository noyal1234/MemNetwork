"""Tests for non-stub bench suites."""

from __future__ import annotations

from brainkm.services.cma_bench import run_cma_suite
from brainkm.services.compaction_bench import run_compaction_suite
from brainkm.services.dmr_bench import run_dmr_suite
from brainkm.services.longmem_bench import run_longmem_suite


def test_dmr_suite_not_stub(tmp_path) -> None:
    db_path = tmp_path / ".brain" / "brain.db"
    result = run_dmr_suite(db_path)
    assert result.total >= 5
    assert not all("stub" in case.detail for case in result.cases)
    assert result.pass_rate >= 0.6


def test_longmem_suite_not_stub(tmp_path) -> None:
    db_path = tmp_path / ".brain" / "brain.db"
    result = run_longmem_suite(db_path)
    assert result.total >= 10
    assert not all("stub" in case.detail for case in result.cases)
    assert result.pass_rate >= 0.6


def test_compaction_suite_not_stub(tmp_path) -> None:
    db_path = tmp_path / ".brain" / "brain.db"
    result = run_compaction_suite(db_path)
    assert result.total >= 3
    assert not all("stub" in case.detail for case in result.cases)
    assert result.pass_rate >= 0.6


def test_cma_suite_not_stub(tmp_path) -> None:
    db_path = tmp_path / ".brain" / "brain.db"
    result = run_cma_suite(db_path)
    assert result.total >= 40
    assert result.pass_rate >= 0.9


def test_fixture_benches_are_rerunnable_against_live_db_path(tmp_path) -> None:
    """TUI passes the project brain path; suites must not UNIQUE-collide on re-run."""
    db_path = tmp_path / ".brain" / "brain.db"
    db_path.parent.mkdir(parents=True)
    db_path.touch()
    for suite in (run_dmr_suite, run_longmem_suite, run_compaction_suite, run_cma_suite):
        first = suite(db_path)
        second = suite(db_path)
        assert first.total > 0
        assert second.total == first.total
        assert second.pass_rate >= 0.6
