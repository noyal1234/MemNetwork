"""Shared helpers for fixture-driven bench suites."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from brainkm.db.connection import connect
from brainkm.db.migrate import migrate
from brainkm.services.memory import create_neuron, get_node


def ephemeral_project_brain() -> tuple[sqlite3.Connection, Path, Path]:
    """Fresh project layout (``project/.brain/brain.db``) for isolated fixture benches.

    Returns ``(conn, db_path, project_dir)``. Caller must close ``conn`` and may
    delete ``project_dir`` when finished.
    """
    root = Path(tempfile.mkdtemp(prefix="brainkm-bench-"))
    db_path = root / ".brain" / "brain.db"
    migrate(db_path=db_path, run_integrity_check=False)
    return connect(db_path), db_path, root


def ensure_fixture_neuron(
    conn: sqlite3.Connection,
    *,
    node_id: str,
    title: str,
    content: str | None = None,
    kind: str = "memory",
    subtype: str | None = "fact",
) -> None:
    """Insert a fixture neuron if missing (idempotent by ``node_id``)."""
    if get_node(conn, node_id) is not None:
        return
    create_neuron(
        conn,
        title=title,
        content=content,
        kind=kind,
        subtype=subtype,
        node_id=node_id,
        source="bench:fixture",
    )


def cleanup_ephemeral_project(project_dir: Path, conn: sqlite3.Connection | None = None) -> None:
    """Close connection and remove ephemeral project tree."""
    import shutil

    if conn is not None:
        conn.close()
    shutil.rmtree(project_dir, ignore_errors=True)
