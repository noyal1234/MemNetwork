"""Hardware-aware recommendation for opt-in semantic retrieval quality."""

from __future__ import annotations

from dataclasses import dataclass

from brainkm.adapters.onnx_models import APPROX_DOWNLOAD_MB
from brainkm.services.hardware import HardwareProfile, detect_hardware

MIN_RAM_GB = 8.0


@dataclass(frozen=True)
class SemanticRecommend:
    recommend_enable: bool
    reason: str
    approx_download_mb: int
    ram_gb: float


def recommend_semantic_profile(
    profile: HardwareProfile | None = None,
) -> SemanticRecommend:
    """Doctor/wizard: recommend MiniLM enable when RAM is known and >= 8GB.

    Never auto-enables — callers must obtain user consent. Cross-encoder is
    never recommended as the default companion toggle.
    """
    resolved = profile or detect_hardware()
    ram = float(resolved.total_ram_gb)
    if ram <= 0.0:
        return SemanticRecommend(
            recommend_enable=False,
            reason="RAM unknown — keep hashing embeddings (zero-dep T0).",
            approx_download_mb=APPROX_DOWNLOAD_MB,
            ram_gb=ram,
        )
    if ram < MIN_RAM_GB:
        return SemanticRecommend(
            recommend_enable=False,
            reason=(
                f"Only {ram:.1f} GB RAM detected (< {MIN_RAM_GB:.0f} GB) — "
                "recommend Skip; FTS + PPR stays on."
            ),
            approx_download_mb=APPROX_DOWNLOAD_MB,
            ram_gb=ram,
        )
    return SemanticRecommend(
        recommend_enable=True,
        reason=(
            f"{ram:.1f} GB RAM — recommended quality is local MiniLM embeddings "
            f"(~{APPROX_DOWNLOAD_MB} MB download). Cross-encoder rerank stays optional."
        ),
        approx_download_mb=APPROX_DOWNLOAD_MB,
        ram_gb=ram,
    )


def format_semantic_recommend(rec: SemanticRecommend) -> str:
    decision = "ENABLE MiniLM" if rec.recommend_enable else "SKIP (keep hashing)"
    return (
        f"Semantic quality recommendation: {decision}\n"
        f"  {rec.reason}\n"
        f"  Approx download: ~{rec.approx_download_mb} MB (cached under ~/.cache/brainkm/onnx/)\n"
        "  Labels: local retrieval embeddings — not an Ollama/chat model."
    )
