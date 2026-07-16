"""Latency bench returns smoke/loaded profiles with variance fields."""

from __future__ import annotations

from pathlib import Path

from brainkm.db.migrate import migrate
from brainkm.db.paths import brain_db_path
from brainkm.services.latency_bench import run_latency_suite


def test_latency_smoke_profile() -> None:
    result = run_latency_suite(Path("/tmp/unused.db"), profile="smoke")
    assert result.suite == "latency-smoke"
    blob = " ".join(f"{c.name} {c.detail}" for c in result.cases)
    assert "smoke_recall_p50" in blob
    assert "±" in blob or "stdev" in blob or "mean=" in blob
    assert "cold_mean=" in blob
    assert result.pass_rate >= 0.8


def test_latency_loaded_shape(tmp_path: Path) -> None:
    migrate(project_dir=tmp_path, run_integrity_check=False)
    result = run_latency_suite(brain_db_path(tmp_path), profile="loaded")
    assert result.suite == "latency-loaded"
    names = {c.name for c in result.cases}
    assert "loaded_recall_p50" in names
    assert any("mean=" in c.detail and "±" in c.detail for c in result.cases)


def test_latency_both_combines(tmp_path: Path) -> None:
    migrate(project_dir=tmp_path, run_integrity_check=False)
    result = run_latency_suite(brain_db_path(tmp_path), profile="both")
    assert result.suite == "latency"
    names = {c.name for c in result.cases}
    assert "smoke_recall_p50" in names
    assert "loaded_recall_p50" in names
