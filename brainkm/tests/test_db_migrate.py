"""Tests for schema migrations."""

from brainkm.db.connection import connect
from brainkm.db.migrate import migrate


def test_migrate_is_idempotent(brain_db) -> None:
    applied_again = migrate(db_path=brain_db, run_integrity_check=False)
    assert applied_again == []


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
