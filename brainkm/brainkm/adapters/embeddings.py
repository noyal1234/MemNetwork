"""Local embedding adapters for T1 hybrid retrieval.

Default: deterministic hashing embedder (zero deps, offline).
Optional: ONNX MiniLM when ``brainkm[semantic]`` (onnxruntime) is installed.
"""

from __future__ import annotations

import hashlib
import math
import struct
from functools import lru_cache
from typing import Protocol

DEFAULT_DIM = 384
HASHING_MODEL = "hashing-v1"
ONNX_MODEL = "minilm-l6-v2-onnx"


class Embedder(Protocol):
    @property
    def model_id(self) -> str: ...

    @property
    def dim(self) -> int: ...

    def embed(self, text: str) -> list[float]: ...


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 0.0:
        return vec
    return [v / norm for v in vec]


class HashingEmbedder:
    """Feature-hashing embedder — always available, deterministic, no model download."""

    def __init__(self, dim: int = DEFAULT_DIM) -> None:
        self._dim = dim

    @property
    def model_id(self) -> str:
        return HASHING_MODEL

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        tokens = text.lower().split()
        if not tokens:
            tokens = ["_empty_"]
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(digest[:4], "little") % self._dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            # Character n-grams for paraphrase-ish collisions on related words
            vec[idx] += sign
            for i in range(len(token) - 2):
                tri = token[i : i + 3]
                td = hashlib.blake2b(tri.encode("utf-8"), digest_size=8).digest()
                tidx = int.from_bytes(td[:4], "little") % self._dim
                tsign = 1.0 if td[4] % 2 == 0 else -1.0
                vec[tidx] += 0.5 * tsign
        return _l2_normalize(vec)


class OnnxMiniLMEmbedder:
    """Optional ONNX MiniLM — loaded lazily; falls back to hashing if unavailable."""

    def __init__(self, dim: int = DEFAULT_DIM) -> None:
        self._dim = dim
        self._session = None
        self._tokenizer = None
        self._failed = False

    @property
    def model_id(self) -> str:
        return ONNX_MODEL if self._session is not None else HASHING_MODEL

    @property
    def dim(self) -> int:
        return self._dim

    def _ensure_session(self) -> bool:
        if self._session is not None:
            return True
        if self._failed:
            return False
        try:
            import onnxruntime as ort  # type: ignore[import-untyped]
        except ImportError:
            self._failed = True
            return False
        # No bundled weights yet — mark failed and use hashing until a model path exists.
        # Keep the import path warm so [semantic] installs don't raise unexpectedly.
        _ = ort
        self._failed = True
        return False

    def embed(self, text: str) -> list[float]:
        if not self._ensure_session():
            return HashingEmbedder(self._dim).embed(text)
        # Placeholder: real ONNX inference would go here once weights are packaged.
        return HashingEmbedder(self._dim).embed(text)


@lru_cache(maxsize=1)
def get_embedder(*, prefer_onnx: bool = True) -> Embedder:
    if prefer_onnx:
        try:
            import onnxruntime  # noqa: F401

            return OnnxMiniLMEmbedder()
        except ImportError:
            pass
    return HashingEmbedder()


def pack_embedding(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def unpack_embedding(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=True))
