"""Local embedding adapters for T1 hybrid retrieval.

Default: deterministic hashing embedder (zero deps, offline).
Optional: ONNX MiniLM when ``brainkm[semantic]`` is installed and weights are cached.
"""

from __future__ import annotations

import hashlib
import math
import struct
from functools import lru_cache
from typing import Protocol

from brainkm.logging_config import get_logger

logger = get_logger("adapters.embeddings")

DEFAULT_DIM = 384
HASHING_MODEL = "hashing-v1"
ONNX_MODEL = "minilm-l6-v2-onnx"
MAX_SEQ_LEN = 128


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
        self._input_names: list[str] = []

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
            import numpy as np
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError:
            self._failed = True
            return False

        from brainkm.adapters.onnx_models import ensure_biencoder

        paths = ensure_biencoder(download=False)
        if paths is None:
            return False
        model_path, tok_path = paths
        try:
            self._tokenizer = Tokenizer.from_file(str(tok_path))
            self._tokenizer.enable_truncation(max_length=MAX_SEQ_LEN)
            self._tokenizer.enable_padding(length=MAX_SEQ_LEN)
            self._session = ort.InferenceSession(
                str(model_path),
                providers=["CPUExecutionProvider"],
            )
            self._input_names = [inp.name for inp in self._session.get_inputs()]
            self._np = np
            self._failed = False
        except Exception:  # noqa: BLE001
            logger.debug("ONNX MiniLM load failed", exc_info=True)
            self._session = None
            self._tokenizer = None
            self._failed = True
            return False
        return True

    def clear_failed(self) -> None:
        """Allow retry after a transient load failure / new weights download."""
        self._failed = False
        self._session = None
        self._tokenizer = None
        self._input_names = []

    def embed(self, text: str) -> list[float]:
        if not self._ensure_session():
            return HashingEmbedder(self._dim).embed(text)
        assert self._tokenizer is not None and self._session is not None
        np = self._np
        encoded = self._tokenizer.encode(text or " ")
        ids = np.array([encoded.ids], dtype=np.int64)
        mask = np.array([encoded.attention_mask], dtype=np.int64)
        feeds: dict[str, object] = {}
        for name in self._input_names:
            lower = name.lower()
            if "token_type" in lower or "type_id" in lower:
                feeds[name] = np.zeros_like(ids)
            elif "mask" in lower:
                feeds[name] = mask
            else:
                feeds[name] = ids
        outputs = self._session.run(None, feeds)
        hidden = outputs[0]
        # Mean-pool over tokens using attention mask.
        if hidden.ndim == 3:
            mask_f = mask.astype(np.float32)
            mask_f = np.expand_dims(mask_f, axis=-1)
            summed = (hidden * mask_f).sum(axis=1)
            counts = np.clip(mask_f.sum(axis=1), a_min=1e-9, a_max=None)
            pooled = summed / counts
            vec = pooled[0].tolist()
        else:
            vec = hidden[0].tolist()
        if len(vec) != self._dim:
            # Unexpected dim — still return L2-normalized vector but record hashing id.
            return _l2_normalize([float(x) for x in vec[: self._dim]] + [0.0] * max(
                0, self._dim - len(vec)
            ))
        return _l2_normalize([float(x) for x in vec])


@lru_cache(maxsize=2)
def get_embedder(*, prefer_onnx: bool = True) -> Embedder:
    """Return hashing or ONNX wrapper.

    ``maxsize=2`` so prefer_onnx True/False callers do not thrash each other.
    """
    if prefer_onnx:
        try:
            import onnxruntime  # noqa: F401

            embedder = OnnxMiniLMEmbedder()
            # Probe once — if weights missing, still return wrapper (falls back per call).
            return embedder
        except ImportError:
            pass
    return HashingEmbedder()


def reset_embedder_cache() -> None:
    """Clear cached embedders and allow ONNX reload after download."""
    get_embedder.cache_clear()


def pack_embedding(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def unpack_embedding(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=True))
