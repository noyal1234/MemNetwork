"""Tests for schema migrations."""

from pathlib import Path

from brainkm.db.connection import connect
from brainkm.db.migrate import apply_migration_sql, migrate, split_sql_statements


def test_migrate_is_idempotent(brain_db) -> None:
    applied_again = migrate(db_path=brain_db, run_integrity_check=False)
    assert applied_again == []


def test_split_sql_keeps_trigger_intact() -> None:
    sql = """
CREATE TABLE t (id TEXT);
CREATE TRIGGER t_ins AFTER INSERT ON t BEGIN
  INSERT INTO t_log VALUES (new.id);
END;
CREATE INDEX idx_t ON t(id);
"""
    stmts = split_sql_statements(sql)
    assert len(stmts) == 3
    assert "CREATE TRIGGER" in stmts[1]
    assert "END;" in stmts[1]


def test_apply_migration_records_version_atomically(tmp_path: Path) -> None:
    """DDL + version insert share one transaction (no executescript auto-commit)."""
    db = tmp_path / "brain.db"
    conn = connect(db)
    try:
        conn.execute(
            """
            CREATE TABLE schema_migrations (
              version TEXT PRIMARY KEY,
              applied_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        apply_migration_sql(
            conn,
            "CREATE TABLE IF NOT EXISTS demo (id TEXT PRIMARY KEY);",
            version="999_demo",
        )
        versions = {
            row[0] for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
        assert "999_demo" in versions
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='demo'").fetchone()
    finally:
        conn.close()


def test_core_tables_exist(brain_db) -> None:
    conn = connect(brain_db)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'trigger')"
            ).fetchall()
        }
        assert "nodes" in tables
        assert "edges" in tables
        assert "audit_log" in tables
        assert "chunk_sources" in tables
        assert "session_snapshots" in tables
        assert "nodes_fts_insert" in tables
        assert "audit_materialize_valid_until" in tables
        assert "audit_materialize_valid_until_forgotten" in tables
    finally:
        conn.close()


def test_foreign_key_cascade_on_forget(brain_db) -> None:
    from tests.conftest import insert_edge, insert_node

    conn = connect(brain_db)
    try:
        insert_node(conn, node_id="n1", title="Auth service")
        insert_node(conn, node_id="n2", title="Payments service")
        insert_edge(conn, edge_id="e1", from_id="n1", to_id="n2")
        conn.commit()

        conn.execute("DELETE FROM nodes WHERE id = ?", ("n1",))
        conn.commit()

        remaining = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        assert remaining == 0
    finally:
        conn.close()
