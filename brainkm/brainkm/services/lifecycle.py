"""Memory lifecycle stages: observation → episode → semantic memory → procedure."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Literal

from brainkm.models.brain_config import BrainConfig
from brainkm.services.memory import forget_neuron, new_ulid, remember_neuron

Stage = Literal["observation", "episode", "semantic", "procedure", "other"]

OBSERVATION_SUBTYPE = "observation"
EPISODE_SUBTYPE = "episode"
SEMANTIC_SUBTYPES = frozenset({"decision", "fact", "rule", "error", "pattern", "context"})


def stage_of(*, kind: str, subtype: str | None) -> Stage:
    if kind == "procedure":
        return "procedure"
    if kind != "memory":
        return "other"
    if subtype == OBSERVATION_SUBTYPE:
        return "observation"
    if subtype == EPISODE_SUBTYPE:
        return "episode"
    if subtype in SEMANTIC_SUBTYPES:
        return "semantic"
    return "other"


def is_working(*, kind: str, subtype: str | None) -> bool:
    return stage_of(kind=kind, subtype=subtype) == "observation"


def is_episodic(*, kind: str, subtype: str | None) -> bool:
    return stage_of(kind=kind, subtype=subtype) == "episode"


def is_semantic(*, kind: str, subtype: str | None) -> bool:
    return stage_of(kind=kind, subtype=subtype) == "semantic"


def insert_distilled_from_edge(
    conn: sqlite3.Connection,
    *,
    from_id: str,
    to_id: str,
    weight: float = 1.0,
) -> str:
    """Link a promoted/distilled neuron to its source observation or episode."""
    edge_id = new_ulid()
    conn.execute(
        """
        INSERT OR IGNORE INTO edges (id, from_id, to_id, relationship, weight, created_at,
            updated_at)
        VALUES (?, ?, ?, 'distilled_from', ?, datetime('now'), datetime('now'))
        """,
        (edge_id, from_id, to_id, weight),
    )
    return edge_id


def create_episode_neuron(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    title: str,
    content: str,
    source: str,
    confidence: float = 0.6,
    tags: list[str] | None = None,
) -> object:
    """Write one episodic digest for a session."""
    return remember_neuron(
        conn,
        title=title[:200],
        content=content,
        kind="memory",
        subtype=EPISODE_SUBTYPE,
        session_id=session_id,
        source=source,
        confidence=confidence,
        tags=tags or ["episode"],
        compress=True,
    )


def archive_expired_observations(
    conn: sqlite3.Connection,
    *,
    config: BrainConfig,
    dry_run: bool = False,
) -> list[str]:
    """Soft-archive unpromoted observations older than observation_ttl_hours."""
    hours = getattr(config.capture, "observation_ttl_hours", 72)
    if hours <= 0:
        return []
    cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    rows = conn.execute(
        """
        SELECT id FROM nodes
        WHERE kind = 'memory'
          AND subtype = ?
          AND valid_until IS NULL
          AND created_at < ?
        ORDER BY created_at ASC
        """,
        (OBSERVATION_SUBTYPE, cutoff),
    ).fetchall()
    archived: list[str] = []
    for (node_id,) in rows:
        archived.append(node_id)
        if not dry_run:
            forget_neuron(
                conn,
                node_id,
                reason=f"lifecycle: observation TTL ({hours}h)",
            )
    return archived
