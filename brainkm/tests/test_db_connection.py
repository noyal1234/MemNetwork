"""Tests for SQLite connection PRAGMA configuration."""

from brainkm.db.connection import connect


def test_connection_enables_foreign_keys_and_wal(brain_db) -> None:
    conn = connect(brain_db)
    try:
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert fk == 1
        assert str(journal).lower() == "wal"
        assert busy == 10000
    finally:
        conn.close()
