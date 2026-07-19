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
    assert summary["neuron_count"] == 0
    assert summary["code_node_count"] == 0
    assert summary["db_size"] != "n/a"
