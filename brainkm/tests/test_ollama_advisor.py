"""Tests for Ollama hardware advisor."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from brainkm.cli import app
from brainkm.models.brain_config import BrainConfig
from brainkm.services.hardware import HardwareProfile
from brainkm.services.ollama_advisor import (
    OllamaStatus,
    apply_recommended_model,
    build_doctor_report,
    format_doctor_report,
    probe_ollama,
    recommend_model,
    resolve_ollama_model,
)


@pytest.mark.parametrize(
    ("profile", "expected_model", "expected_tier"),
    [
        (
            HardwareProfile(6.0, 4, "darwin", "x86_64", False),
            "qwen2.5:1.5b-instruct-q4_K_M",
            "minimal",
        ),
        (
            HardwareProfile(16.0, 6, "darwin", "x86_64", False),
            "qwen2.5:3b",
            "small",
        ),
        (
            HardwareProfile(16.0, 8, "darwin", "arm64", True),
            "qwen2.5:3b",
            "small",
        ),
        (
            HardwareProfile(24.0, 10, "linux", "x86_64", True),
            "qwen2.5:7b-instruct-q4_K_M",
            "medium",
        ),
        (
            HardwareProfile(32.0, 12, "darwin", "arm64", True),
            "qwen2.5:14b-instruct-q4_K_M",
            "large",
        ),
    ],
)
def test_recommend_model_tiers(
    profile: HardwareProfile,
    expected_model: str,
    expected_tier: str,
) -> None:
    rec = recommend_model(profile)
    assert rec.model == expected_model
    assert rec.tier == expected_tier


def test_recommend_model_unknown_ram_defaults_small() -> None:
    profile = HardwareProfile(0.0, 6, "darwin", "x86_64", False)
    rec = recommend_model(profile)
    assert rec.model == "qwen2.5:3b"
    assert rec.tier == "small"


def test_probe_ollama_unreachable() -> None:
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
        status = probe_ollama("http://127.0.0.1:11434")
    assert status.reachable is False


def test_probe_ollama_lists_models() -> None:
    class FakeResponse:
        status_code = 200

        @staticmethod
        def json() -> dict:
            return {"models": [{"name": "qwen2.5:3b"}, {"name": "qwen2.5:1.5b-instruct-q4_K_M"}]}

    class FakeClient:
        @staticmethod
        def get(url: str, timeout: float) -> FakeResponse:
            return FakeResponse()

    fake_httpx = type("httpx", (), {"get": FakeClient.get})
    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        status = probe_ollama("http://127.0.0.1:11434")

    assert status.reachable is True
    assert status.installed_models == ("qwen2.5:3b", "qwen2.5:1.5b-instruct-q4_K_M")


def test_resolve_ollama_model_uses_config_when_auto_select_disabled() -> None:
    cfg = BrainConfig(ollama={"model": "custom:7b", "auto_select_model": False})
    assert resolve_ollama_model(cfg) == "custom:7b"


def test_resolve_ollama_model_auto_selects_from_hardware() -> None:
    cfg = BrainConfig(ollama={"model": "custom:7b", "auto_select_model": True})
    profile = HardwareProfile(16.0, 6, "darwin", "x86_64", False)

    with patch("brainkm.services.ollama_advisor.detect_hardware", return_value=profile):
        assert resolve_ollama_model(cfg) == "qwen2.5:3b"


def test_resolve_ollama_model_falls_back_when_ram_unknown() -> None:
    cfg = BrainConfig(ollama={"model": "custom:7b", "auto_select_model": True})
    profile = HardwareProfile(0.0, 6, "darwin", "x86_64", False)

    with patch("brainkm.services.ollama_advisor.detect_hardware", return_value=profile):
        assert resolve_ollama_model(cfg) == "custom:7b"


def test_ollama_distill_adapter_uses_resolved_model() -> None:
    from brainkm.adapters.ollama_distill import OllamaDistillAdapter

    cfg = BrainConfig(
        capture={"distill_mode": "ollama"},
        ollama={"model": "configured:3b", "auto_select_model": True},
    )
    profile = HardwareProfile(16.0, 6, "darwin", "x86_64", False)

    with patch("brainkm.services.ollama_advisor.detect_hardware", return_value=profile):
        adapter = OllamaDistillAdapter(cfg)

    assert adapter._model == "qwen2.5:3b"


def test_format_doctor_report_mismatch_warning() -> None:
    profile = HardwareProfile(16.0, 6, "darwin", "x86_64", False)
    report = build_doctor_report(profile=profile)
    report = report.__class__(
        profile=profile,
        recommendation=recommend_model(profile),
        ollama=OllamaStatus(reachable=True, installed_models=("qwen2.5:3b",)),
        config_model="qwen2.5:7b-instruct-q4_K_M",
        config_path=Path(".brain/config.json"),
    )
    text = format_doctor_report(report)
    assert "differs" in text
    assert "qwen2.5:3b" in text


def test_apply_recommended_model_updates_config(tmp_path: Path) -> None:
    brain_dir = tmp_path / ".brain"
    brain_dir.mkdir()
    cfg_path = brain_dir / "config.json"
    cfg_path.write_text(
        json.dumps({"ollama": {"model": "old:1b"}}, indent=2) + "\n",
        encoding="utf-8",
    )

    profile = HardwareProfile(16.0, 6, "darwin", "x86_64", False)
    rec = recommend_model(profile)
    updated = apply_recommended_model(project_dir=tmp_path, recommendation=rec)

    assert updated == cfg_path
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert data["ollama"]["model"] == "qwen2.5:3b"


def test_ollama_doctor_cli(tmp_path: Path) -> None:
    brain_dir = tmp_path / ".brain"
    brain_dir.mkdir()
    (brain_dir / "config.json").write_text(
        json.dumps({"ollama": {"model": "qwen2.5:3b", "base_url": "http://127.0.0.1:11434"}}),
        encoding="utf-8",
    )

    runner = CliRunner()
    profile = HardwareProfile(16.0, 6, "darwin", "x86_64", False)
    ollama = OllamaStatus(reachable=True, installed_models=("qwen2.5:3b",))

    with (
        patch("brainkm.services.ollama_advisor.detect_hardware", return_value=profile),
        patch("brainkm.services.ollama_advisor.probe_ollama", return_value=ollama),
    ):
        result = runner.invoke(app, ["ollama", "doctor", "--project-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert "Recommended model: qwen2.5:3b" in result.output
    assert "matches recommendation" in result.output


def test_ollama_doctor_cli_missing_config(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["ollama", "doctor", "--project-dir", str(tmp_path)])
    assert result.exit_code == 1
