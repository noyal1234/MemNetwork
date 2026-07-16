"""Latency bench returns structured p50/p95 metrics."""

from __future__ import annotations

from pathlib import Path

from brainkm.db.migrate import migrate
from brainkm.db.paths import brain_db_path
from brainkm.services.latency_bench import run_latency_suite


def test_latency_suite_shape(tmp_path: Path) -> None:
    migrate(project_dir=tmp_path, run_integrity_check=False)
    result = run_latency_suite(brain_db_path(tmp_path))
    assert result.suite == "latency"
    assert result.cases
    blob = " ".join(f"{c.name} {c.detail}" for c in result.cases)
    assert "p50" in blob or "p95" in blob or "recall" in blob.lower()
