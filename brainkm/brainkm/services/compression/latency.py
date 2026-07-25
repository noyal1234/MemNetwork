"""Latency microbench for compression stages (Phase 0 gate input)."""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass

from brainkm.services.compression.pipeline import compress_text
from brainkm.services.compression.rtk_lite import compress_tool_log


@dataclass(frozen=True)
class LatencyReport:
    stage: str
    samples: int
    p50_ms: float
    p95_ms: float
    max_ms: float


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((p / 100.0) * (len(ordered) - 1)))))
    return ordered[idx]


def microbench_rtk(tool_log: str, *, rounds: int = 50) -> LatencyReport:
    samples: list[float] = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        compress_tool_log(tool_log, project_dir=None)
        samples.append((time.perf_counter() - t0) * 1000.0)
    return LatencyReport(
        stage="rtk_lite",
        samples=rounds,
        p50_ms=_percentile(samples, 50),
        p95_ms=_percentile(samples, 95),
        max_ms=max(samples) if samples else 0.0,
    )


def microbench_pipeline(text: str, *, rounds: int = 50) -> LatencyReport:
    samples: list[float] = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        compress_text(text, kind="memory", subtype="observation")
        samples.append((time.perf_counter() - t0) * 1000.0)
    return LatencyReport(
        stage="pipeline",
        samples=rounds,
        p50_ms=statistics.median(samples) if samples else 0.0,
        p95_ms=_percentile(samples, 95),
        max_ms=max(samples) if samples else 0.0,
    )
