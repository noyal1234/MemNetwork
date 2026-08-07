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


def test_probe_groq_rate_limited() -> None:
    class FakeResponse:
        status_code = 429
        headers = {"retry-after": "7"}
        text = '{"error":{"message":"Rate limit reached","code":"rate_limit_exceeded"}}'

        def json(self) -> dict:
            return {
                "error": {
                    "message": "Rate limit reached for model",
                    "code": "rate_limit_exceeded",
                }
            }

    fake_httpx = type(
        "httpx",
        (),
        {"post": staticmethod(lambda *a, **k: FakeResponse())},
    )
    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        status = probe_groq("https://api.groq.com/openai/v1", "gsk_test")
    assert status.reachable is False
    assert status.rate_limited is True
    assert "429" in (status.error or "")
    assert "retry-after 7s" in (status.error or "")


def test_is_rate_limit_error() -> None:
    from brainkm.services.groq_advisor import is_rate_limit_error

    assert is_rate_limit_error("rate limited (429)") is True
    assert is_rate_limit_error("unauthorized") is False
    assert is_rate_limit_error(None) is False


def test_probe_groq_unreachable() -> None:
    fake_httpx = type(
        "httpx",
        (),
        {"post": staticmethod(lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("down")))},
    )
    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        status = probe_groq("https://api.groq.com/openai/v1", "gsk_test")
    assert status.reachable is False


def test_probe_groq_chat_ok() -> None:
    class FakeResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json() -> dict:
            return {"choices": [{"message": {"content": "ok"}}]}

    posts: list[dict] = []

    class FakeClient:
        @staticmethod
        def post(
            url: str,
            *,
            json: dict | None = None,
            headers: dict | None = None,
            timeout: float = 0,
        ) -> FakeResponse:
            posts.append({"url": url, "json": json})
            return FakeResponse()

    fake_httpx = type("httpx", (), {"post": FakeClient.post})
    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        status = probe_groq(
            "https://api.groq.com/openai/v1",
            "gsk_test",
            model="llama-3.3-70b-versatile",
        )

    assert status.reachable is True
    assert status.models == ("llama-3.3-70b-versatile",)
    assert posts and posts[0]["url"].endswith("/chat/completions")
    assert posts[0]["json"]["model"] == "llama-3.3-70b-versatile"
    assert posts[0]["json"]["max_tokens"] == 1


def test_probe_groq_models_list_403_not_used() -> None:
    """Regression: GET /models 403 must not make the probe fail when chat works."""

    class FakeResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json() -> dict:
            return {"choices": [{"message": {"content": "x"}}]}

    class FakeClient:
        @staticmethod
        def get(*args, **kwargs):  # pragma: no cover - must not be called
            raise AssertionError("probe must not use GET /models")

        @staticmethod
        def post(*args, **kwargs) -> FakeResponse:
            return FakeResponse()

    fake_httpx = type("httpx", (), {"get": FakeClient.get, "post": FakeClient.post})
    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        status = probe_groq("https://api.groq.com/openai/v1", "gsk_test")
    assert status.reachable is True


def test_format_groq_report_missing_key() -> None:
    # Pass empty string (not None) so env/.env GROQ_API_KEY cannot leak into the report.
    report = build_groq_report(api_key="")
    text = format_groq_report(report)
    assert "API key: missing" in text
    assert "Free tier" in text


def test_build_groq_report_loads_project_env_when_cwd_differs(
    tmp_path: Path, monkeypatch
) -> None:
    """Regression: doctor/configure --project-dir must see my-app/.env, not cwd."""
    import os

    from brainkm.config import get_settings

    project = tmp_path / "my-app"
    other = tmp_path / "other-cwd"
    project.mkdir()
    other.mkdir()
    (project / ".brain").mkdir()
    (project / ".brain" / "config.json").write_text("{}\n", encoding="utf-8")
    (project / ".env").write_text("GROQ_API_KEY=gsk_from_project_env\n", encoding="utf-8")

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    get_settings.cache_clear()
    old = Path.cwd()
    try:
        os.chdir(other)
        get_settings.cache_clear()
        assert get_settings().groq_api_key is None
        status = GroqStatus(reachable=True, models=("llama-3.3-70b-versatile",))
        with patch("brainkm.services.groq_advisor.probe_groq", return_value=status):
            report = build_groq_report(project_dir=project)
        assert report.api_key_present is True
        assert report.api_key_masked == "gsk_..._env"
    finally:
        os.chdir(old)
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        get_settings.cache_clear()


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
