"""Local ONNX model cache for MiniLM bi-encoder and MS-MARCO cross-encoder.

Models live under ``~/.cache/brainkm/onnx/`` (not the project tree). Downloads
are opt-in via ``ensure_*`` helpers used by doctor / wizard consent.
"""

from __future__ import annotations

import os
from pathlib import Path

from brainkm.logging_config import get_logger

logger = get_logger("adapters.onnx_models")

# Primary then fallback (transformers.js / onnx-community mirrors often publish ONNX).
_BIENCODER_CANDIDATES: tuple[tuple[str, str, str], ...] = (
    ("sentence-transformers/all-MiniLM-L6-v2", "onnx/model.onnx", "tokenizer.json"),
    ("Xenova/all-MiniLM-L6-v2", "onnx/model.onnx", "tokenizer.json"),
)
_CROSS_ENCODER_CANDIDATES: tuple[tuple[str, str, str], ...] = (
    ("Xenova/ms-marco-MiniLM-L-6-v2", "onnx/model.onnx", "tokenizer.json"),
    ("cross-encoder/ms-marco-MiniLM-L-6-v2", "onnx/model.onnx", "tokenizer.json"),
)

APPROX_DOWNLOAD_MB = 90


def onnx_cache_dir() -> Path:
    override = os.environ.get("BRAINKM_ONNX_CACHE")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".cache" / "brainkm" / "onnx"


def biencoder_paths() -> tuple[Path, Path]:
    root = onnx_cache_dir() / "minilm-l6-v2"
    return root / "model.onnx", root / "tokenizer.json"


def cross_encoder_paths() -> tuple[Path, Path]:
    root = onnx_cache_dir() / "ms-marco-minilm-l6"
    return root / "model.onnx", root / "tokenizer.json"


def biencoder_cached() -> bool:
    model, tok = biencoder_paths()
    return model.is_file() and tok.is_file()


def cross_encoder_cached() -> bool:
    model, tok = cross_encoder_paths()
    return model.is_file() and tok.is_file()


def _hf_download(repo_id: str, filename: str, dest: Path) -> None:
    from huggingface_hub import hf_hub_download

    dest.parent.mkdir(parents=True, exist_ok=True)
    downloaded = hf_hub_download(repo_id=repo_id, filename=filename)
    src = Path(downloaded)
    if dest.resolve() != src.resolve():
        dest.write_bytes(src.read_bytes())


def _download_first(
    candidates: tuple[tuple[str, str, str], ...],
    model_dest: Path,
    tok_dest: Path,
) -> bool:
    last_error: Exception | None = None
    for repo_id, model_file, tok_file in candidates:
        try:
            _hf_download(repo_id, model_file, model_dest)
            _hf_download(repo_id, tok_file, tok_dest)
            if model_dest.is_file() and tok_dest.is_file():
                logger.info("Cached ONNX model from %s", repo_id)
                return True
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.debug("ONNX download candidate failed repo=%s: %s", repo_id, exc)
    if last_error is not None:
        logger.warning("All ONNX download candidates failed: %s", last_error)
    return False


def ensure_biencoder(*, download: bool = True) -> tuple[Path, Path] | None:
    """Return (model, tokenizer) paths if available; download when requested."""
    model, tok = biencoder_paths()
    if model.is_file() and tok.is_file():
        return model, tok
    if not download:
        return None
    if not _download_first(_BIENCODER_CANDIDATES, model, tok):
        return None
    return model, tok


def ensure_cross_encoder(*, download: bool = True) -> tuple[Path, Path] | None:
    model, tok = cross_encoder_paths()
    if model.is_file() and tok.is_file():
        return model, tok
    if not download:
        return None
    if not _download_first(_CROSS_ENCODER_CANDIDATES, model, tok):
        return None
    return model, tok


def ensure_semantic_models(*, include_cross_encoder: bool = False) -> dict[str, bool]:
    """Download consent-time models. Returns readiness flags."""
    be = ensure_biencoder(download=True) is not None
    ce = False
    if include_cross_encoder:
        ce = ensure_cross_encoder(download=True) is not None
    try:
        from brainkm.adapters.embeddings import get_embedder
        from brainkm.services.rerank import reset_cross_encoder_cache

        get_embedder.cache_clear()
        reset_cross_encoder_cache()
    except Exception:  # noqa: BLE001
        pass
    return {"biencoder": be, "cross_encoder": ce}
