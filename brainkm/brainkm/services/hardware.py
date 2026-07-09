"""Host hardware profile detection for Ollama model selection."""

from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass


@dataclass(frozen=True)
class HardwareProfile:
    total_ram_gb: float
    cpu_cores: int
    platform: str
    arch: str
    has_gpu_accel: bool


def _detect_gpu_accel(sys_platform: str, arch: str) -> bool:
    if sys_platform == "darwin" and arch == "arm64":
        return True
    return shutil.which("nvidia-smi") is not None


def detect_hardware() -> HardwareProfile:
    """Return host RAM, CPU, and GPU-acceleration hints.

    When ``psutil`` is unavailable, ``total_ram_gb`` is ``0.0`` (unknown).
    """
    sys_platform = platform.system().lower()
    arch = platform.machine().lower()
    cpu_cores = os.cpu_count() or 1
    has_gpu_accel = _detect_gpu_accel(sys_platform, arch)

    try:
        import psutil

        total_bytes = psutil.virtual_memory().total
        total_ram_gb = round(total_bytes / (1024**3), 1)
    except (ImportError, AttributeError):
        total_ram_gb = 0.0

    return HardwareProfile(
        total_ram_gb=total_ram_gb,
        cpu_cores=cpu_cores,
        platform=sys_platform,
        arch=arch,
        has_gpu_accel=has_gpu_accel,
    )
