"""Diversify ranked recall/pack hits by session_id and kind."""

from __future__ import annotations

from collections import defaultdict
from typing import Protocol, TypeVar


class _HasKindSession(Protocol):
    node_id: str
    kind: str
    session_id: str | None


T = TypeVar("T", bound=_HasKindSession)


def diversify_ranked(
    items: list[T],
    *,
    max_per_session: int = 3,
    max_per_kind: dict[str, int] | None = None,
    pinned_ids: set[str] | None = None,
) -> list[T]:
    """Keep score order but cap per session and per kind. Pinned ids always kept."""
    if not items:
        return []
    kind_caps = max_per_kind or {}
    pinned = pinned_ids or set()
    session_counts: dict[str, int] = defaultdict(int)
    kind_counts: dict[str, int] = defaultdict(int)
    kept: list[T] = []
    for item in items:
        if item.node_id in pinned:
            kept.append(item)
            continue
        sid = item.session_id or ""
        if sid and session_counts[sid] >= max_per_session:
            continue
        kind_cap = kind_caps.get(item.kind)
        if kind_cap is not None and kind_counts[item.kind] >= kind_cap:
            continue
        kept.append(item)
        if sid:
            session_counts[sid] += 1
        kind_counts[item.kind] += 1
    return kept
