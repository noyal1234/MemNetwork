"""Models for frozen SessionStart injection snapshots."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SnapshotNeuron:
    node_id: str
    kind: str
    subtype: str | None
    title: str
    content: str | None
    token_count: int


@dataclass(frozen=True)
class InjectionSnapshot:
    session_id: str
    neuron_ids: tuple[str, ...]
    pack_text: str
    token_count: int
    created_at: str
    frozen: bool = True
