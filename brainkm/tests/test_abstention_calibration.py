"""Tests for bench fixture abstention calibration."""

from __future__ import annotations

from pathlib import Path

import pytest

from brainkm.db.connection import connect
from brainkm.models.brain_config import RecallConfig
from brainkm.services.abstention import resolve_corpus_threshold, should_abstain_for_query
from brainkm.services.abstention_calibrate import (
    calibrate_abstention,
    calibrate_reference,
    load_abstention_fixture,
    load_calibration,
    load_package_fixture,
    save_calibration,
    seed_fixture_corpus,
)
from brainkm.services.search import recall_with_bfs


def test_package_fixture_loads() -> None:
    fixture = load_package_fixture()
    assert fixture.id == "abstention_v1"
    assert len(fixture.corpus) >= 5
    assert len(fixture.queries) >= 8


def test_calibrate_abstention_passes_all_fixture_queries(brain_db) -> None:
    fixture = load_package_fixture()
    conn = connect(brain_db)
    try:
        calibration = calibrate_abstention(conn, RecallConfig(), fixture, seed_corpus=True)
        conn.commit()
    finally:
        conn.close()

    assert calibration.query_pass_rate == 1.0
    assert calibration.corpus_bm25_threshold is not None
    assert calibration.min_recall_score is not None
    assert calibration.min_recall_score > 0


def test_saved_calibration_used_at_recall_time(tmp_path: Path, brain_db) -> None:
    fixture = load_package_fixture()
    conn = connect(brain_db)
    try:
        calibration = calibrate_abstention(conn, RecallConfig(), fixture, seed_corpus=True)
        conn.commit()
    finally:
        conn.close()

    save_calibration(calibration, brain_db.parent.parent)

    conn = connect(brain_db)
    try:
        project_dir = brain_db.parent.parent
        threshold = resolve_corpus_threshold(conn, RecallConfig(), project_dir=project_dir)
        # Uses the least-strict candidate among live/rolling/calibration.
        assert threshold is not None
        assert threshold >= calibration.corpus_bm25_threshold

        weak = should_abstain_for_query(
            conn,
            [-0.01],
            RecallConfig(),
            project_dir=project_dir,
        )
        strong = should_abstain_for_query(
            conn,
            [-50.0],
            RecallConfig(),
            project_dir=project_dir,
        )
        assert weak is True
        assert strong is False
    finally:
        conn.close()


def test_recall_with_bfs_respects_calibration(tmp_path: Path, brain_db) -> None:
    fixture = load_package_fixture()
    conn = connect(brain_db)
    try:
        seed_fixture_corpus(conn, fixture)
        conn.commit()
        calibration = calibrate_abstention(conn, RecallConfig(), fixture, seed_corpus=False)
        conn.commit()
    finally:
        conn.close()

    save_calibration(calibration, tmp_path)

    conn = connect(brain_db)
    try:
        confident = recall_with_bfs(
            conn,
            "JWT access token expiry",
            project_dir=tmp_path,
        )
        abstained = recall_with_bfs(
            conn,
            "quantum banana reactor flux",
            project_dir=tmp_path,
        )
        assert len(confident.nodes) >= 1
        assert abstained.nodes == []
    finally:
        conn.close()


def test_calibrate_reference_writes_project_file(tmp_path: Path) -> None:
    brain_root = tmp_path / ".brain"
    brain_root.mkdir()
    calibration = calibrate_reference(project_dir=tmp_path)

    loaded = load_calibration(tmp_path)
    assert loaded is not None
    assert loaded.fixture_id == calibration.fixture_id
    assert loaded.query_pass_rate == 1.0


def test_load_rolling_scores_ignores_corrupt_entries(tmp_path: Path) -> None:
    from brainkm.services.abstention_calibrate import (
        _load_rolling_scores,
        rolling_scores_path,
    )

    brain = tmp_path / ".brain"
    brain.mkdir()
    path = rolling_scores_path(tmp_path)
    path.write_text('[-5.0, " ", -10.0, null]', encoding="utf-8")
    assert _load_rolling_scores(path) == [-5.0, -10.0]


def test_fixture_file_roundtrip() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "brainkm"
        / "bench"
        / "fixtures"
        / "abstention_v1.json"
    )
    fixture = load_abstention_fixture(path)
    assert any(item.expected_node_id == "jwt-policy" for item in fixture.queries)


def test_calibrate_fails_without_corpus(brain_db) -> None:
    fixture = load_package_fixture()
    conn = connect(brain_db)
    try:
        with pytest.raises(Exception):
            calibrate_abstention(conn, RecallConfig(), fixture, seed_corpus=False)
    finally:
        conn.close()
