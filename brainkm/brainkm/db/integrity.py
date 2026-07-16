"""FTS5 integrity checks for external-content virtual tables."""

from __future__ import annotations

import sqlite3

from brainkm.logging_config import get_logger

logger = get_logger("db.integrity")

FTS_TABLES = ("nodes_fts", "session_fts")


class FtsIntegrityError(RuntimeError):
    """Raised when FTS5 integrity-check reports mismatches."""


def check_fts_table(conn: sqlite3.Connection, table: str) -> list[tuple]:
    """Run FTS5 integrity-check for one virtual table."""
    cursor = conn.execute(f"INSERT INTO {table}({table}) VALUES('integrity-check')")
    return list(cursor.fetchall())


def check_fts_integrity(conn: sqlite3.Connection) -> dict[str, list[tuple]]:
    """Run FTS5 integrity-check on configured tables.

    Returns a mapping of table name to mismatch rows (empty when healthy).
    Logs WARNING for any non-empty result.
    """
    issues: dict[str, list[tuple]] = {}

    for table in FTS_TABLES:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        if not exists:
            continue

        rows = check_fts_table(conn, table)
        if rows:
            logger.warning("FTS integrity mismatch in %s: %d row(s)", table, len(rows))
            issues[table] = rows

    return issues
