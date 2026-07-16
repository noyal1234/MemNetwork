"""Tests for semantic quality advisor and recommendation thresholds."""

from __future__ import annotations

from brainkm.services.hardware import HardwareProfile
from brainkm.services.semantic_advisor import recommend_semantic_profile


def _profile(ram: float) -> HardwareProfile:
    return HardwareProfile(
        total_ram_gb=ram,
        cpu_cores=4,
        platform="darwin",
        arch="arm64",
        has_gpu_accel=True,
    )


def test_recommend_skip_unknown_ram() -> None:
    rec = recommend_semantic_profile(_profile(0.0))
    assert rec.recommend_enable is False
    assert "unknown" in rec.reason.lower() or "unknown" in rec.reason


def test_recommend_skip_low_ram() -> None:
    rec = recommend_semantic_profile(_profile(4.0))
    assert rec.recommend_enable is False


def test_recommend_enable_high_ram() -> None:
    rec = recommend_semantic_profile(_profile(16.0))
    assert rec.recommend_enable is True
    assert rec.approx_download_mb > 0
