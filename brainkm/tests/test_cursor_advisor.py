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


def test_ensure_cursor_agent_path_idempotent(tmp_path: Path, monkeypatch) -> None:
    import os

    from brainkm.services import cursor_advisor

    local = tmp_path / ".local" / "bin"
    local.mkdir(parents=True)
    monkeypatch.setattr(cursor_advisor, "local_bin_dir", lambda: local)
    monkeypatch.setenv("PATH", "/usr/bin")

    assert cursor_advisor.ensure_cursor_agent_path() is True
    assert str(local) in os.environ["PATH"]
    # Second call should be a no-op (still true, no duplicate storm)
    first = os.environ["PATH"]
    assert cursor_advisor.ensure_cursor_agent_path() is True
    assert os.environ["PATH"] == first


def test_probe_finds_local_bin_agent(tmp_path: Path, monkeypatch) -> None:
    local = tmp_path / ".local" / "bin"
    local.mkdir(parents=True)
    agent = local / "agent"
    agent.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    agent.chmod(0o755)

    with patch(
        "brainkm.services.cursor_advisor.resolve_cursor_agent_bin",
        return_value=str(agent),
    ):
        status = probe_cursor_agent()
    assert status.found is True
    assert status.bin_path == str(agent)


def test_install_skips_network_when_already_present() -> None:
    from brainkm.services.cursor_advisor import install_cursor_agent_cli

    with (
        patch(
            "brainkm.services.cursor_advisor.probe_cursor_agent",
            return_value=CursorStatus(found=True, bin_path="/usr/bin/agent", bin_name="agent"),
        ),
        patch("brainkm.services.cursor_advisor.subprocess.run") as run_mock,
    ):
        result = install_cursor_agent_cli()
    assert result.ok is True
    assert result.found is True
    assert result.stdout_tail == "already installed"
    run_mock.assert_not_called()


def test_install_runs_script_and_reprobes() -> None:
    from brainkm.services.cursor_advisor import install_cursor_agent_cli

    class _Completed:
        returncode = 0
        stdout = "installed ok"
        stderr = ""

    with (
        patch("brainkm.services.cursor_advisor.shutil.which", return_value="/bin/bash"),
        patch(
            "brainkm.services.cursor_advisor.probe_cursor_agent",
            side_effect=[
                CursorStatus(found=False),
                CursorStatus(found=True, bin_path="/home/u/.local/bin/agent", bin_name="agent"),
            ],
        ),
        patch(
            "brainkm.services.cursor_advisor._download_cursor_install_script",
        ) as download_mock,
        patch(
            "brainkm.services.cursor_advisor.subprocess.run",
            return_value=_Completed(),
        ) as run_mock,
    ):
        result = install_cursor_agent_cli()
    assert result.ok is True
    assert result.found is True
    download_mock.assert_called_once()
    run_mock.assert_called_once()
    argv = run_mock.call_args[0][0]
    assert argv[0] == "bash"
    assert run_mock.call_args.kwargs.get("shell") in (None, False)


def test_cli_cursor_install(tmp_path: Path) -> None:
    from brainkm.services.cursor_advisor import CursorInstallResult

    brain_dir = tmp_path / ".brain"
    brain_dir.mkdir()
    (brain_dir / "config.json").write_text(
        json.dumps({"version": 1, "capture": {"distill_mode": "cursor"}}),
        encoding="utf-8",
    )
    runner = CliRunner()
    with (
        patch(
            "brainkm.services.cursor_advisor.install_cursor_agent_cli",
            return_value=CursorInstallResult(
                ok=True,
                found=True,
                bin_path="/tmp/agent",
                stdout_tail="already installed",
            ),
        ),
        patch(
            "brainkm.services.cursor_advisor.probe_cursor_agent",
            return_value=CursorStatus(found=True, bin_path="/tmp/agent", bin_name="agent"),
        ),
    ):
        result = runner.invoke(app, ["cursor", "install", "--project-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "Agent found" in result.stdout or "found" in result.stdout.lower()
