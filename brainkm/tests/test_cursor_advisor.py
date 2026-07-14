"""Tests for Cursor agent CLI distill advisor."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from brainkm.cli import app
from brainkm.services.cursor_advisor import (
    CursorStatus,
    build_cursor_doctor_report,
    format_cursor_report,
    probe_cursor_agent,
)


def test_probe_cursor_agent_not_found() -> None:
    with patch(
        "brainkm.services.cursor_advisor.resolve_cursor_agent_bin",
        return_value=None,
    ):
        status = probe_cursor_agent()
    assert status.found is False
    assert status.bin_path is None


def test_probe_cursor_agent_found() -> None:
    with patch(
        "brainkm.services.cursor_advisor.resolve_cursor_agent_bin",
        return_value="/usr/local/bin/agent",
    ):
        status = probe_cursor_agent()
    assert status.found is True
    assert status.bin_name == "agent"
    assert status.bin_path == "/usr/local/bin/agent"


def test_format_cursor_report_without_agent(tmp_path: Path) -> None:
    brain_dir = tmp_path / ".brain"
    brain_dir.mkdir()
    (brain_dir / "config.json").write_text(
        json.dumps({"capture": {"distill_mode": "cursor"}}),
        encoding="utf-8",
    )
    with patch(
        "brainkm.services.cursor_advisor.resolve_cursor_agent_bin",
        return_value=None,
    ):
        report = build_cursor_doctor_report(project_dir=tmp_path)
    text = format_cursor_report(report)
    assert "not found" in text
    assert "heuristic distill" in text
    assert "Config distill_mode: cursor" in text


def test_format_cursor_report_with_agent(tmp_path: Path) -> None:
    brain_dir = tmp_path / ".brain"
    brain_dir.mkdir()
    (brain_dir / "config.json").write_text(
        json.dumps({"capture": {"distill_mode": "cursor"}}),
        encoding="utf-8",
    )
    with patch(
        "brainkm.services.cursor_advisor.resolve_cursor_agent_bin",
        return_value="/opt/homebrew/bin/cursor-agent",
    ):
        report = build_cursor_doctor_report(project_dir=tmp_path)
    text = format_cursor_report(report)
    assert "found" in text
    assert "cursor-agent" in text
    assert "LLM-quality Cursor distill: available" in text


def test_cli_cursor_doctor(tmp_path: Path) -> None:
    brain_dir = tmp_path / ".brain"
    brain_dir.mkdir()
    (brain_dir / "config.json").write_text(
        json.dumps({"version": 1, "capture": {"distill_mode": "cursor"}}),
        encoding="utf-8",
    )
    runner = CliRunner()
    with patch(
        "brainkm.services.cursor_advisor.resolve_cursor_agent_bin",
        return_value=None,
    ):
        result = runner.invoke(app, ["cursor", "doctor", "--project-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "Cursor agent CLI" in result.stdout


def test_cli_cursor_doctor_missing_config(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["cursor", "doctor", "--project-dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "Config not found" in result.stdout or "Config not found" in result.stderr
