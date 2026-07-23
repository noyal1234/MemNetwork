"""Hashing embedder always works; ONNX path soft-falls back without weights."""

from __future__ import annotations

from pathlib import Path

import pytest

from brainkm.adapters.embeddings import (
    HASHING_MODEL,
    HashingEmbedder,
    OnnxMiniLMEmbedder,
    cosine_similarity,
    get_embedder,
)


def test_hashing_embedder_deterministic() -> None:
    e = HashingEmbedder()
    a = e.embed("hello world")
    b = e.embed("hello world")
    assert a == b
    assert e.model_id == HASHING_MODEL
    assert abs(cosine_similarity(a, a) - 1.0) < 1e-6


def test_get_embedder_cache_holds_both_prefer_flags() -> None:
    from brainkm.adapters.embeddings import reset_embedder_cache

    reset_embedder_cache()
    hashing = get_embedder(prefer_onnx=False)
    onnx_or_hash = get_embedder(prefer_onnx=True)
    hashing_again = get_embedder(prefer_onnx=False)
    assert isinstance(hashing, HashingEmbedder)
    assert hashing_again is hashing  # cached
    # prefer_onnx=True may still be hashing wrapper if onnxruntime missing —
    # either way it must not evict the False cache entry.
    assert get_embedder(prefer_onnx=False) is hashing
    _ = onnx_or_hash


def test_onnx_embedder_falls_back_without_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Isolate from the developer's real ~/.cache/brainkm/onnx weights.
    monkeypatch.setenv("BRAINKM_ONNX_CACHE", str(tmp_path / "empty-onnx"))
    get_embedder.cache_clear()
    emb = OnnxMiniLMEmbedder()
    vec = emb.embed("test phrase")
    assert len(vec) == 384
    # Without cached weights, model_id stays hashing.
    assert emb.model_id == HASHING_MODEL
