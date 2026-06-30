"""Deterministic ULID generator for bench tests."""

from __future__ import annotations

import ulid


class SeededUlidGenerator:
    def __init__(self, seed: int = 0) -> None:
        self._counter = seed

    def next(self) -> str:
        self._counter += 1
        return str(ulid.from_timestamp(self._counter))


_seeded: SeededUlidGenerator | None = None


def enable_seeded_ulids(seed: int = 1) -> SeededUlidGenerator:
    global _seeded
    _seeded = SeededUlidGenerator(seed)
    return _seeded


def disable_seeded_ulids() -> None:
    global _seeded
    _seeded = None


def new_ulid() -> str:
    if _seeded is not None:
        return _seeded.next()
    return str(ulid.new())
