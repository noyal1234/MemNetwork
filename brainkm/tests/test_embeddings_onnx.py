"""Hashing embedder always works; ONNX path soft-falls back without weights."""

from __future__ import annotations

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


def test_get_embedder_cache_clear() -> None:
    get_embedder.cache_clear()
    first = get_embedder(prefer_onnx=False)
    assert isinstance(first, HashingEmbedder)


def test_onnx_embedder_falls_back_without_cache() -> None:
    get_embedder.cache_clear()
    emb = OnnxMiniLMEmbedder()
    vec = emb.embed("test phrase")
    assert len(vec) == 384
    # Without cached weights, model_id stays hashing.
    assert emb.model_id == HASHING_MODEL
