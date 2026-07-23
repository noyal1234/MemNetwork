"""Prefetch WebLLM / MLC model weights for offline viz chat.

Downloads Hugging Face `mlc-ai/<model_id>` artifacts into a user-level cache
(`~/.cache/brainkm/webllm/<model_id>/`) so `brainkm viz` can serve them locally.
The WASM model library remains on the MLC CDN (small); only multi-GB weights are prefetched.

Browser still loads weights into WebGPU on first Ask of a session, but the heavy
internet download happens once during setup (wizard) or via the service API.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from brainkm.logging_config import get_logger

logger = get_logger("webllm_prefetch")

# Keep in sync with viz_static/chat.js model picker + @mlc-ai/web-llm prebuiltAppConfig.
WEBLLM_MODELS: dict[str, dict[str, str]] = {
    "Llama-3.2-3B-Instruct-q4f16_1-MLC": {
        "label": "Llama 3.2 3B — best quality (~2 GB, needs more VRAM)",
        "hf_repo": "mlc-ai/Llama-3.2-3B-Instruct-q4f16_1-MLC",
        "model_lib": "Llama-3.2-3B-Instruct-q4f16_1_cs1k-webgpu.wasm",
        "size_hint": "~2 GB",
    },
    "Llama-3.2-1B-Instruct-q4f16_1-MLC": {
        "label": "Llama 3.2 1B — recommended laptop balance (~1 GB)",
        "hf_repo": "mlc-ai/Llama-3.2-1B-Instruct-q4f16_1-MLC",
        "model_lib": "Llama-3.2-1B-Instruct-q4f16_1_cs1k-webgpu.wasm",
        "size_hint": "~1 GB",
    },
    "SmolLM2-360M-Instruct-q4f16_1-MLC": {
        "label": "SmolLM2 360M — lightest / weakest (~0.3 GB)",
        "hf_repo": "mlc-ai/SmolLM2-360M-Instruct-q4f16_1-MLC",
        "model_lib": "SmolLM2-360M-Instruct-q4f16_1_cs1k-webgpu.wasm",
        "size_hint": "~0.3 GB",
    },
}

DEFAULT_MODEL_ID = "Llama-3.2-1B-Instruct-q4f16_1-MLC"

# Match @mlc-ai/web-llm@0.2.79+ prebuilt libs (wasm stays on CDN).
_MODEL_LIB_PREFIX = (
    "https://raw.githubusercontent.com/mlc-ai/binary-mlc-llm-libs/main/web-llm-models/v0_2_84/base/"
)

ProgressCallback = Callable[[str, int, int], None]  # (filename, done_files, total_files)


def webllm_cache_root() -> Path:
    """User-level cache so one download serves all projects."""
    override = os.environ.get("BRAINKM_WEBLLM_CACHE")
    if override:
        return Path(override).expanduser().resolve()
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg).expanduser().resolve() / "brainkm" / "webllm"
    return Path.home() / ".cache" / "brainkm" / "webllm"


def model_cache_dir(model_id: str) -> Path:
    return webllm_cache_root() / model_id


def is_model_cached(model_id: str) -> bool:
    """True if essential config + at least one weight shard exists."""
    d = model_cache_dir(model_id)
    config = d / "mlc-chat-config.json"
    if not config.is_file():
        return False
    # ndarray-cache + params, or any .bin / .safetensors
    if (d / "ndarray-cache.json").is_file():
        return True
    return any(d.glob("*.bin")) or any(d.glob("params_shard_*"))


def model_lib_url(model_id: str) -> str:
    meta = WEBLLM_MODELS.get(model_id)
    if not meta:
        raise KeyError(f"Unknown WebLLM model: {model_id}")
    return _MODEL_LIB_PREFIX + meta["model_lib"]


@dataclass(frozen=True)
class PrefetchResult:
    model_id: str
    cache_dir: Path
    files_downloaded: int
    files_skipped: int
    bytes_downloaded: int
    already_cached: bool
    error: str | None = None


def _hf_headers() -> dict[str, str]:
    headers = {"User-Agent": "brainkm-webllm-prefetch/0.3"}
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _list_hf_files(repo: str) -> list[str]:
    """List files in an HF model repo (flat + one level of subdirs)."""
    api = f"https://huggingface.co/api/models/{repo}/tree/main"
    req = urllib.request.Request(api, headers=_hf_headers())
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
        entries = json.loads(resp.read().decode())

    files: list[str] = []
    for entry in entries:
        etype = entry.get("type")
        path = entry.get("path")
        if not path:
            continue
        if etype == "file":
            files.append(path)
        elif etype == "directory":
            sub_api = f"https://huggingface.co/api/models/{repo}/tree/main/{path}"
            sub_req = urllib.request.Request(sub_api, headers=_hf_headers())
            with urllib.request.urlopen(sub_req, timeout=60) as sub_resp:  # noqa: S310
                for sub in json.loads(sub_resp.read().decode()):
                    if sub.get("type") == "file" and sub.get("path"):
                        files.append(sub["path"])
    return files


def _download_file(url: str, dest: Path) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    req = urllib.request.Request(url, headers=_hf_headers())
    written = 0
    with urllib.request.urlopen(req, timeout=300) as resp:  # noqa: S310
        with tmp.open("wb") as out:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                written += len(chunk)
    tmp.replace(dest)
    return written


def prefetch_webllm_model(
    model_id: str,
    *,
    force: bool = False,
    progress: ProgressCallback | None = None,
) -> PrefetchResult:
    """Download MLC weight artifacts for ``model_id`` into the user cache."""
    if model_id not in WEBLLM_MODELS:
        return PrefetchResult(
            model_id=model_id,
            cache_dir=model_cache_dir(model_id),
            files_downloaded=0,
            files_skipped=0,
            bytes_downloaded=0,
            already_cached=False,
            error=f"Unknown model id: {model_id}",
        )

    dest_root = model_cache_dir(model_id)
    if is_model_cached(model_id) and not force:
        logger.info("WebLLM model already cached: %s (%s)", model_id, dest_root)
        return PrefetchResult(
            model_id=model_id,
            cache_dir=dest_root,
            files_downloaded=0,
            files_skipped=0,
            bytes_downloaded=0,
            already_cached=True,
        )

    repo = WEBLLM_MODELS[model_id]["hf_repo"]
    try:
        files = _list_hf_files(repo)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return PrefetchResult(
            model_id=model_id,
            cache_dir=dest_root,
            files_downloaded=0,
            files_skipped=0,
            bytes_downloaded=0,
            already_cached=False,
            error=f"Failed to list Hugging Face repo {repo}: {exc}",
        )

    if not files:
        return PrefetchResult(
            model_id=model_id,
            cache_dir=dest_root,
            files_downloaded=0,
            files_skipped=0,
            bytes_downloaded=0,
            already_cached=False,
            error=f"No files found in {repo}",
        )

    dest_root.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    skipped = 0
    total_bytes = 0
    total = len(files)

    for i, rel in enumerate(files, start=1):
        if progress:
            progress(rel, i - 1, total)
        target = dest_root / rel
        if target.is_file() and not force:
            skipped += 1
            continue
        url = f"https://huggingface.co/{repo}/resolve/main/{rel}"
        try:
            total_bytes += _download_file(url, target)
            downloaded += 1
            logger.info("Downloaded %s (%d/%d)", rel, i, total)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # Clean partial
            partial = target.with_suffix(target.suffix + ".partial")
            if partial.exists():
                partial.unlink(missing_ok=True)
            return PrefetchResult(
                model_id=model_id,
                cache_dir=dest_root,
                files_downloaded=downloaded,
                files_skipped=skipped,
                bytes_downloaded=total_bytes,
                already_cached=False,
                error=f"Failed downloading {rel}: {exc}",
            )

    if progress:
        progress("done", total, total)

    ok = is_model_cached(model_id)
    return PrefetchResult(
        model_id=model_id,
        cache_dir=dest_root,
        files_downloaded=downloaded,
        files_skipped=skipped,
        bytes_downloaded=total_bytes,
        already_cached=ok and downloaded == 0,
        error=None if ok else "Download finished but mlc-chat-config.json missing",
    )


def webllm_engine_config(model_id: str, *, local_model_base_url: str) -> dict[str, Any]:
    """Build a WebLLM ``appConfig.model_list`` entry for local viz serving."""
    if model_id not in WEBLLM_MODELS:
        raise KeyError(model_id)
    base = local_model_base_url.rstrip("/") + "/"
    return {
        "model": base,
        "model_id": model_id,
        "model_lib": model_lib_url(model_id),
    }


def status_summary(model_id: str | None = None) -> dict[str, Any]:
    mid = model_id or DEFAULT_MODEL_ID
    return {
        "model_id": mid,
        "known": mid in WEBLLM_MODELS,
        "cached": is_model_cached(mid) if mid in WEBLLM_MODELS else False,
        "cache_dir": str(model_cache_dir(mid)),
        "label": WEBLLM_MODELS.get(mid, {}).get("label"),
        "models": [
            {
                "id": k,
                "label": v["label"],
                "size_hint": v["size_hint"],
                "cached": is_model_cached(k),
            }
            for k, v in WEBLLM_MODELS.items()
        ],
    }
