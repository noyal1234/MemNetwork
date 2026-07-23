"""Tests for WebLLM model prefetch + viz config wiring."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.request import urlopen

import pytest

from brainkm.models.brain_config import BrainConfig, VizConfig
from brainkm.services import webllm_prefetch as wp
from brainkm.services.viz import start_viz_server


def test_viz_config_defaults() -> None:
    cfg = BrainConfig()
    assert cfg.viz.webllm_model == "Llama-3.2-1B-Instruct-q4f16_1-MLC"
    assert cfg.viz.webllm_prefetch is True


def test_brain_config_accepts_viz_section() -> None:
    cfg = BrainConfig(
        viz=VizConfig(webllm_model="SmolLM2-360M-Instruct-q4f16_1-MLC", webllm_prefetch=False)
    )
    assert cfg.viz.webllm_model.startswith("SmolLM2")


def test_is_model_cached_false_without_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BRAINKM_WEBLLM_CACHE", str(tmp_path))
    assert wp.is_model_cached("Llama-3.2-1B-Instruct-q4f16_1-MLC") is False


def test_is_model_cached_true_with_essentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BRAINKM_WEBLLM_CACHE", str(tmp_path))
    mid = "Llama-3.2-1B-Instruct-q4f16_1-MLC"
    d = tmp_path / mid
    d.mkdir(parents=True)
    (d / "mlc-chat-config.json").write_text("{}", encoding="utf-8")
    (d / "ndarray-cache.json").write_text("{}", encoding="utf-8")
    assert wp.is_model_cached(mid) is True


def test_prefetch_skips_when_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAINKM_WEBLLM_CACHE", str(tmp_path))
    mid = "Llama-3.2-1B-Instruct-q4f16_1-MLC"
    d = tmp_path / mid
    d.mkdir(parents=True)
    (d / "mlc-chat-config.json").write_text("{}", encoding="utf-8")
    (d / "ndarray-cache.json").write_text("{}", encoding="utf-8")

    result = wp.prefetch_webllm_model(mid)
    assert result.already_cached is True
    assert result.error is None
    assert result.files_downloaded == 0


def test_prefetch_unknown_model() -> None:
    result = wp.prefetch_webllm_model("not-a-real-model")
    assert result.error
    assert "Unknown" in result.error


def test_viz_webllm_config_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BRAINKM_WEBLLM_CACHE", str(tmp_path))
    monkeypatch.setattr("webbrowser.open", lambda *_a, **_k: True)

    mid = "Llama-3.2-1B-Instruct-q4f16_1-MLC"
    d = tmp_path / mid
    d.mkdir(parents=True)
    (d / "mlc-chat-config.json").write_text('{"model":"x"}', encoding="utf-8")
    (d / "ndarray-cache.json").write_text("{}", encoding="utf-8")
    (d / "tokenizer.json").write_text("{}", encoding="utf-8")

    handle = start_viz_server(demo=True, open_browser=False, port=0)
    try:
        with urlopen(  # noqa: S310
            f"{handle.base_url}/api/webllm-config?token={handle.token}",
            timeout=2,
        ) as resp:
            data = json.loads(resp.read().decode())
        assert data["cached"] is True
        assert data["use_local"] is True
        assert "app_config" in data
        assert data["app_config"]["model_list"][0]["model"].startswith("http://")

        with urlopen(  # noqa: S310
            f"{handle.base_url}/models/{mid}/mlc-chat-config.json?token={handle.token}",
            timeout=2,
        ) as resp:
            assert b'"model"' in resp.read()
    finally:
        handle.stop()
