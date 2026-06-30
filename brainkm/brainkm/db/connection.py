"""SQLite connection factory with required PRAGMA settings."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from brainkm.db.paths import brain_db_path


def configure_connection(conn: sqlite3.Connection) -> None:
    """Apply PRAGMA settings required for correct MemNetwork behavior."""
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.row_factory = sqlite3.Row


def connect(
    db_path: Path | None = None,
    *,
    project_dir: Path | None = None,
) -> sqlite3.Connection:
    """Open a SQLite connection to the project brain database."""
    path = db_path if db_path is not None else brain_db_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    configure_connection(conn)
    return conn


@contextmanager
def connection(
    db_path: Path | None = None,
    *,
    project_dir: Path | None = None,
) -> Iterator[sqlite3.Connection]:
    """Context manager that closes the connection on exit."""
    conn = connect(db_path, project_dir=project_dir)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
