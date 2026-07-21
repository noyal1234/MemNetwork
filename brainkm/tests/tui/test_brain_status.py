"""Unit tests for services.brain_status (TUI dashboard sidebar)."""

from __future__ import annotations

from pathlib import Path

from brainkm.services.brain_status import build_brain_status_summary


def test_build_brain_status_summary_on_fresh_brain(tui_project: Path) -> None:
    summary = build_brain_status_summary(tui_project)
    assert "distill_mode" in summary
    assert "neuron_count" in summary
    assert "code_node_count" in summary
    assert "db_size" in summary
    assert "commit_trace_label" in summary
    assert "commit_trace_color" in summary
    assert summary["neuron_count"] == 0
    assert summary["code_node_count"] == 0
    assert summary["db_size"] != "n/a"
    assert summary["commit_trace_label"] in {"on", "off", "on · no hook", "skipped", "?"}


def test_build_brain_status_commit_trace_off_when_grandfathered(tmp_path: Path) -> None:
    import json

    from brainkm.db.migrate import migrate

    migrate(project_dir=tmp_path, run_integrity_check=False)
    brain = tmp_path / ".brain"
    brain.mkdir(parents=True, exist_ok=True)
    (brain / "config.json").write_text(
        json.dumps({"git": {"enabled": False}}, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = build_brain_status_summary(tmp_path)
    assert summary["commit_trace"] is False
    assert summary["commit_trace_label"] == "off"
