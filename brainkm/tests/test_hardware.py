"""Tests for hardware profile detection."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

from brainkm.services.hardware import HardwareProfile, detect_hardware


def test_detect_hardware_returns_profile_with_psutil() -> None:
    mock_psutil = MagicMock()
    mock_psutil.virtual_memory.return_value = MagicMock(total=16 * 1024**3)

    with patch.dict(sys.modules, {"psutil": mock_psutil}):
        profile = detect_hardware()

    assert isinstance(profile, HardwareProfile)
    assert profile.total_ram_gb == 16.0
    assert profile.cpu_cores >= 1
    assert profile.platform in {"darwin", "linux", "windows"}
    assert profile.arch


def test_detect_hardware_graceful_fallback_without_psutil() -> None:
    with patch.dict(sys.modules, {"psutil": None}):
        profile = detect_hardware()

    assert profile.total_ram_gb == 0.0
    assert profile.cpu_cores >= 1


def test_detect_gpu_accel_apple_silicon() -> None:
    from brainkm.services.hardware import _detect_gpu_accel

    assert _detect_gpu_accel("darwin", "arm64") is True


def test_detect_gpu_accel_intel_mac() -> None:
    from brainkm.services.hardware import _detect_gpu_accel

    with patch("brainkm.services.hardware.shutil.which", return_value=None):
        assert _detect_gpu_accel("darwin", "x86_64") is False
