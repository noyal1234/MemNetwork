"""ONNX model cache helpers — no network downloads in tests."""

from __future__ import annotations

from pathlib import Path

from brainkm.adapters import onnx_models


def test_onnx_cache_dir_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BRAINKM_ONNX_CACHE", str(tmp_path / "onnx"))
    assert onnx_models.onnx_cache_dir() == (tmp_path / "onnx").resolve()


def test_ensure_biencoder_no_download_miss(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BRAINKM_ONNX_CACHE", str(tmp_path / "empty-cache"))
    assert onnx_models.ensure_biencoder(download=False) is None
    assert onnx_models.biencoder_cached() is False


def test_ensure_cross_encoder_no_download_miss(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BRAINKM_ONNX_CACHE", str(tmp_path / "empty-cache"))
    assert onnx_models.ensure_cross_encoder(download=False) is None
    assert onnx_models.cross_encoder_cached() is False


def test_biencoder_paths_under_cache(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BRAINKM_ONNX_CACHE", str(tmp_path))
    model, tok = onnx_models.biencoder_paths()
    assert model.parent.name == "minilm-l6-v2"
    assert tok.name == "tokenizer.json"
