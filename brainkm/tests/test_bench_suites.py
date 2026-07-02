"""Tests for non-stub bench suites."""

from __future__ import annotations

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
