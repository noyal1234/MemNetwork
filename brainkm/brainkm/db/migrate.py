"""Apply ordered SQL migrations to the project brain database."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from brainkm.db.connection import connect
from brainkm.db.integrity import FtsIntegrityError, check_fts_integrity
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


def split_sql_statements(sql: str) -> list[str]:
    """Split migration SQL into executable statements.

    Keeps ``CREATE TRIGGER ... BEGIN ... END;`` blocks intact (semicolons
    inside the trigger body must not split the statement).
    """
    statements: list[str] = []
    buf: list[str] = []
    in_trigger = False

    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped and not buf:
            continue
        if stripped.startswith("--") and not buf and not in_trigger:
            continue

        upper = stripped.upper()
        if upper.startswith("CREATE TRIGGER"):
            in_trigger = True

        buf.append(line)

        if in_trigger:
            # Trigger body ends at a line that is exactly END; (optional whitespace).
            if upper == "END;" or upper.rstrip() == "END;":
                statements.append("\n".join(buf).strip())
                buf = []
                in_trigger = False
        elif stripped.endswith(";"):
            statements.append("\n".join(buf).strip())
            buf = []

    trailing = "\n".join(buf).strip()
    if trailing:
        statements.append(trailing)

    return [s for s in statements if s and s != ";"]


def apply_migration_sql(conn: sqlite3.Connection, sql: str, *, version: str) -> None:
    """Apply one migration + version row in a single transaction.

    Avoids ``executescript`` which auto-commits before the version insert.
    """
    statements = split_sql_statements(sql)
    conn.execute("BEGIN IMMEDIATE")
    try:
        for statement in statements:
            conn.execute(statement)
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (version, datetime.now(UTC).isoformat()),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


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
        conn.commit()
        applied = _applied_versions(conn)
        newly_applied: list[str] = []

        for migration_path in _migration_files():
            version = migration_path.stem
            if version in applied:
                continue

            sql = migration_path.read_text(encoding="utf-8")
            logger.info("Applying migration %s", version)
            apply_migration_sql(conn, sql, version=version)
            newly_applied.append(version)

        if run_integrity_check and newly_applied:
            issues = check_fts_integrity(conn)
            if issues:
                detail = ", ".join(f"{t}={len(rows)}" for t, rows in issues.items())
                raise FtsIntegrityError(f"FTS integrity check failed after migrate: {detail}")

        return newly_applied
    finally:
        conn.close()


def current_schema_version(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None
