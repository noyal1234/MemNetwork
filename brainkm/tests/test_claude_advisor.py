"""Tests for the Claude Code CLI wizard advisor."""

from __future__ import annotations

from unittest.mock import patch

from brainkm.services.claude_advisor import (
    ClaudeCliStatus,
    format_claude_cli_report,
    install_claude_cli,
    probe_claude_cli,
)


def test_probe_claude_cli_not_found() -> None:
    with patch("brainkm.services.claude_advisor.resolve_claude_bin", return_value=None):
        status = probe_claude_cli()
    assert status.found is False
    assert status.bin_path is None


def test_probe_claude_cli_found() -> None:
    with patch(
        "brainkm.services.claude_advisor.resolve_claude_bin",
        return_value="/usr/local/bin/claude",
    ):
        status = probe_claude_cli()
    assert status.found is True
    assert status.bin_path == "/usr/local/bin/claude"


def test_format_claude_cli_report_without_cli() -> None:
    text = format_claude_cli_report(ClaudeCliStatus(found=False))
    assert "not found" in text
    assert "npm install -g @anthropic-ai/claude-code" in text


def test_format_claude_cli_report_with_cli() -> None:
    text = format_claude_cli_report(ClaudeCliStatus(found=True, bin_path="/usr/bin/claude"))
    assert "found" in text
    assert "/usr/bin/claude" in text


def test_install_skips_npm_when_already_present() -> None:
    with (
        patch(
            "brainkm.services.claude_advisor.probe_claude_cli",
            return_value=ClaudeCliStatus(found=True, bin_path="/usr/bin/claude"),
        ),
        patch("brainkm.services.claude_advisor.subprocess.run") as run_mock,
    ):
        result = install_claude_cli()
    assert result.ok is True
    assert result.found is True
    assert result.stdout_tail == "already installed"
    run_mock.assert_not_called()


def test_install_errors_when_npm_missing() -> None:
    with (
        patch(
            "brainkm.services.claude_advisor.probe_claude_cli",
            side_effect=[ClaudeCliStatus(found=False)],
        ),
        patch("brainkm.services.claude_advisor.shutil.which", return_value=None),
    ):
        result = install_claude_cli()
    assert result.ok is False
    assert result.found is False
    assert "npm not found" in (result.error or "")


def test_install_runs_npm_and_reprobes() -> None:
    class _Completed:
        returncode = 0
        stdout = "+ @anthropic-ai/claude-code@1.0.0"
        stderr = ""

    with (
        patch("brainkm.services.claude_advisor.shutil.which", return_value="/usr/bin/npm"),
        patch(
            "brainkm.services.claude_advisor.probe_claude_cli",
            side_effect=[
                ClaudeCliStatus(found=False),
                ClaudeCliStatus(found=True, bin_path="/usr/local/bin/claude"),
            ],
        ),
        patch(
            "brainkm.services.claude_advisor.subprocess.run",
            return_value=_Completed(),
        ) as run_mock,
    ):
        result = install_claude_cli()
    assert result.ok is True
    assert result.found is True
    argv = run_mock.call_args[0][0]
    assert argv == ["npm", "install", "-g", "@anthropic-ai/claude-code"]


def test_install_reports_error_when_still_not_found() -> None:
    class _Completed:
        returncode = 1
        stdout = ""
        stderr = "network error"

    with (
        patch("brainkm.services.claude_advisor.shutil.which", return_value="/usr/bin/npm"),
        patch(
            "brainkm.services.claude_advisor.probe_claude_cli",
            side_effect=[ClaudeCliStatus(found=False), ClaudeCliStatus(found=False)],
        ),
        patch(
            "brainkm.services.claude_advisor.subprocess.run",
            return_value=_Completed(),
        ),
    ):
        result = install_claude_cli()
    assert result.ok is False
    assert result.found is False
    assert result.error is not None
