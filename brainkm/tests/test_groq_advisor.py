"""Tests for Groq cloud distill advisor."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from brainkm.cli import app
from brainkm.services.groq_advisor import (
    GroqStatus,
    build_groq_report,
    format_groq_report,
    mask_api_key,
    probe_groq,
)


def test_mask_api_key() -> None:
    assert mask_api_key(None) is None
    assert mask_api_key("short") == "***"
    assert mask_api_key("gsk_abcdefghijklmnop") == "gsk_...mnop"


def test_probe_groq_missing_key() -> None:
    status = probe_groq("https://api.groq.com/openai/v1", None)
    assert status.reachable is False
    assert status.error == "GROQ_API_KEY not set"


def test_probe_groq_unreachable() -> None:
    fake_httpx = type(
        "httpx",
        (),
        {
            "get": staticmethod(
                lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("down"))
            )
        },
    )
    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        status = probe_groq("https://api.groq.com/openai/v1", "gsk_test")
    assert status.reachable is False


def test_probe_groq_lists_models() -> None:
    class FakeResponse:
        status_code = 200

        @staticmethod
        def json() -> dict:
            return {"data": [{"id": "llama-3.3-70b-versatile"}, {"id": "llama-3.1-8b-instant"}]}

    class FakeClient:
        @staticmethod
        def get(url: str, headers: dict | None = None, timeout: float = 0) -> FakeResponse:
            return FakeResponse()

    fake_httpx = type("httpx", (), {"get": FakeClient.get})
    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        status = probe_groq("https://api.groq.com/openai/v1", "gsk_test")

    assert status.reachable is True
    assert status.models == ("llama-3.3-70b-versatile", "llama-3.1-8b-instant")


def test_format_groq_report_missing_key() -> None:
    report = build_groq_report(api_key=None)
    text = format_groq_report(report)
    assert "API key: missing" in text
    assert "Free tier" in text


def test_format_groq_report_reachable(tmp_path: Path) -> None:
    brain_dir = tmp_path / ".brain"
    brain_dir.mkdir()
    (brain_dir / "config.json").write_text(
        json.dumps(
            {
                "groq": {
                    "model": "llama-3.3-70b-versatile",
                    "base_url": "https://api.groq.com/openai/v1",
                }
            }
        ),
        encoding="utf-8",
    )
    status = GroqStatus(reachable=True, models=("llama-3.3-70b-versatile",))
    with patch("brainkm.services.groq_advisor.probe_groq", return_value=status):
        report = build_groq_report(project_dir=tmp_path, api_key="gsk_abcdefghijklmnop")
    text = format_groq_report(report)
    assert "API key: present (gsk_...mnop)" in text
    assert "Groq reachable: yes" in text
    assert "Config model: llama-3.3-70b-versatile" in text


def test_groq_doctor_cli_missing_key(tmp_path: Path) -> None:
    brain_dir = tmp_path / ".brain"
    brain_dir.mkdir()
    (brain_dir / "config.json").write_text(
        json.dumps({"groq": {"model": "llama-3.3-70b-versatile"}}),
        encoding="utf-8",
    )
    runner = CliRunner()
    with patch("brainkm.services.groq_advisor.get_settings") as mock_settings:
        mock_settings.return_value.groq_api_key = None
        result = runner.invoke(app, ["groq", "doctor", "--project-dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "API key: missing" in result.output


def test_groq_doctor_cli_ok(tmp_path: Path) -> None:
    brain_dir = tmp_path / ".brain"
    brain_dir.mkdir()
    (brain_dir / "config.json").write_text(
        json.dumps({"groq": {"model": "llama-3.3-70b-versatile"}}),
        encoding="utf-8",
    )
    status = GroqStatus(reachable=True, models=("llama-3.3-70b-versatile",))
    runner = CliRunner()
    with (
        patch("brainkm.services.groq_advisor.get_settings") as mock_settings,
        patch("brainkm.services.groq_advisor.probe_groq", return_value=status),
    ):
        mock_settings.return_value.groq_api_key = "gsk_abcdefghijklmnop"
        result = runner.invoke(app, ["groq", "doctor", "--project-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "Groq reachable: yes" in result.output


def test_groq_doctor_cli_missing_config(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["groq", "doctor", "--project-dir", str(tmp_path)])
    assert result.exit_code == 1
