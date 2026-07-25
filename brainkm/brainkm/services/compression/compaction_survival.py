"""Host compaction survival — only where local transcripts exist."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CompactionSurvival:
    """Result of comparing SessionStart neuron ids vs end-of-session presence."""

    availability: str  # "supported" | "unsupported"
    host: str
    started_ids: tuple[str, ...]
    survived_ids: tuple[str, ...]
    rate: float | None

    @property
    def scored(self) -> bool:
        return self.availability == "supported" and self.rate is not None


def survival_for_host(
    host: str,
    *,
    started_neuron_ids: list[str],
    end_of_session_present_ids: list[str] | None,
) -> CompactionSurvival:
    """Score survival only for Claude Code / Codex CLI transcript paths.

    Cursor / Antigravity IDE → unsupported (never fake 0%).
    """
    normalized = (host or "").strip().lower()
    if normalized not in {"claude", "codex"}:
        return CompactionSurvival(
            availability="unsupported",
            host=normalized or "unknown",
            started_ids=tuple(started_neuron_ids),
            survived_ids=(),
            rate=None,
        )
    if end_of_session_present_ids is None:
        return CompactionSurvival(
            availability="unsupported",
            host=normalized,
            started_ids=tuple(started_neuron_ids),
            survived_ids=(),
            rate=None,
        )
    started = set(started_neuron_ids)
    present = set(end_of_session_present_ids)
    survived = tuple(sorted(started & present))
    rate = (len(survived) / len(started)) if started else 1.0
    return CompactionSurvival(
        availability="supported",
        host=normalized,
        started_ids=tuple(sorted(started)),
        survived_ids=survived,
        rate=rate,
    )
