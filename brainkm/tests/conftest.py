"""Shared pytest fixtures for brainkm database tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from brainkm.db.migrate import migrate


@pytest.fixture
def brain_db(tmp_path: Path) -> Path:
    db_path = tmp_path / ".brain" / "brain.db"
    migrate(db_path=db_path, run_integrity_check=True)
    return db_path


def insert_node(
    conn,
    *,
    node_id: str,
    kind: str = "memory",
    subtype: str | None = "fact",
    title: str,
    content: str = "",
    path: str | None = None,
) -> None:
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """
        INSERT INTO nodes (
          id, kind, subtype, title, content, path, ingested_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (node_id, kind, subtype, title, content, path, now, now, now),
    )


def insert_edge(
    conn,
    *,
    edge_id: str,
    from_id: str,
    to_id: str,
    relationship: str = "relates_to",
    weight: float = 1.0,
) -> None:
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """
        INSERT INTO edges (id, from_id, to_id, relationship, weight, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (edge_id, from_id, to_id, relationship, weight, now, now),
    )
