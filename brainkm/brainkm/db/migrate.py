"""Apply ordered SQL migrations to the project brain database."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from brainkm.db.connection import connect
from brainkm.db.integrity import check_fts_integrity
from brainkm.db.paths import brain_db_path, migrations_dir
from brainkm.logging_config import get_logger

logger = get_logger("db.migrate")


def _ensure_schema_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version    TEXT PRIMARY KEY,
          applied_at TEXT NOT NULL
        )
        """
    )


def _applied_versions(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {row[0] for row in rows}


def _migration_files() -> list[Path]:
    return sorted(migrations_dir().glob("*.sql"))


def migrate(
    db_path: Path | None = None,
    *,
    project_dir: Path | None = None,
    run_integrity_check: bool = True,
) -> list[str]:
    """Apply pending migrations. Returns list of newly applied version labels."""
    path = db_path if db_path is not None else brain_db_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = connect(path)
    try:
        _ensure_schema_migrations(conn)
        applied = _applied_versions(conn)
        newly_applied: list[str] = []

        for migration_path in _migration_files():
            version = migration_path.stem
            if version in applied:
                continue

            sql = migration_path.read_text(encoding="utf-8")
            logger.info("Applying migration %s", version)
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, datetime.now(UTC).isoformat()),
            )
            conn.commit()
            newly_applied.append(version)

        if run_integrity_check and newly_applied:
            check_fts_integrity(conn)

        return newly_applied
    finally:
        conn.close()


def current_schema_version(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None
