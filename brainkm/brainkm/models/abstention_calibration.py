"""Persisted abstention thresholds calibrated from bench fixtures."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AbstentionCalibration(BaseModel):
    """Bench-calibrated BM25 thresholds stored in `.brain/abstention_calibration.json`."""

    version: int = Field(default=1, ge=1)
    fixture_id: str
    abstain_percentile: float = Field(ge=0.0, le=1.0)
    corpus_bm25_threshold: float | None = None
    min_recall_score: float | None = Field(default=None, ge=0.0, le=100.0)
    query_pass_count: int = Field(default=0, ge=0)
    query_total: int = Field(default=0, ge=0)
    calibrated_at: str

    @property
    def query_pass_rate(self) -> float:
        if self.query_total == 0:
            return 1.0
        return self.query_pass_count / self.query_total
