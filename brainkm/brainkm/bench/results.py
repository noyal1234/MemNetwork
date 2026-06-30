"""Shared bench result types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BenchCaseResult:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class BenchSuiteResult:
    suite: str
    passed: int
    total: int
    cases: list[BenchCaseResult]

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 1.0
