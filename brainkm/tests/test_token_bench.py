"""Tests for token and budget bench suites."""

from __future__ import annotations

from pathlib import Path

import pytest

from brainkm.services.bench_runner import run_bench_suite
from brainkm.services.token_bench import (
    evaluate_token_case,
    load_package_token_fixture,
    measure_baseline_tokens,
    probe_context_pack,
)
from tests.conftest import insert_node


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_load_token_fixture_has_ten_cases() -> None:
    fixture = load_package_token_fixture()
    assert fixture.id == "token_v1"
    assert len(fixture.cases) == 10
    assert fixture.budget_probe is not None


def test_measure_baseline_uses_files_when_present(repo_root: Path) -> None:
    case = load_package_token_fixture().cases[0]
    live = measure_baseline_tokens(repo_root, case.baseline_files)
    assert live >= case.baseline_tokens or 0  # type: ignore[operator]
    assert live > 1000


def test_measure_baseline_falls_back_without_files(tmp_path: Path) -> None:
    total = measure_baseline_tokens(
        tmp_path,
        ["missing/a.py", "missing/b.py"],
        fallback=9999,
    )
    assert total == 9999


def test_token_suite_passes_against_repo(brain_db) -> None:
    result = run_bench_suite("token", brain_db)
    assert result.total == 10
    assert result.pass_rate == 1.0


def test_budget_suite_monotonic_and_critical_node(brain_db) -> None:
    result = run_bench_suite("budget", brain_db)
    assert result.total >= 8
    cap_800 = next(case for case in result.cases if case.name == "cap_800")
    cap_1500 = next(case for case in result.cases if case.name == "cap_1500")
    assert cap_800.passed is True
    assert cap_1500.passed is True
    assert "omitted=9" in cap_800.detail
    monotonic = [case for case in result.cases if case.name.startswith("monotonic_")]
    assert all(case.passed for case in monotonic)


def test_evaluate_token_case_respects_cap(brain_db, repo_root: Path) -> None:
    from brainkm.db.connection import connect

    fixture = load_package_token_fixture()
    case = fixture.cases[0]
    conn = connect(brain_db)
    try:
        outcome = evaluate_token_case(
            conn,
            case,
            project_dir=repo_root,
            min_reduction_pct=0.5,
            max_pack_tokens=1500,
        )
        assert outcome.passed is True
        assert "pack=" in outcome.detail
        assert "baseline=" in outcome.detail
    finally:
        conn.close()


def test_probe_context_pack_on_brain_db(brain_db) -> None:
    from brainkm.db.connection import connect

    conn = connect(brain_db)
    try:
        insert_node(
            conn,
            node_id="live-jwt",
            subtype="decision",
            title="JWT expiry policy",
            content="Use 15 minute access tokens with refresh rotation",
        )
        conn.commit()
    finally:
        conn.close()

    result = probe_context_pack(brain_db, "JWT expiry policy")
    assert result.passed is True
    assert "pack=" in result.detail


def test_token_suite_live_mode(brain_db) -> None:
    from brainkm.db.connection import connect

    conn = connect(brain_db)
    try:
        insert_node(
            conn,
            node_id="live-rule",
            subtype="rule",
            title="WAL checkpoint rule",
            content="Run wal_checkpoint before handover",
        )
        conn.commit()
    finally:
        conn.close()

    result = run_bench_suite("token", brain_db, live=True)
    assert result.suite == "token-live"
    assert result.total == 10
