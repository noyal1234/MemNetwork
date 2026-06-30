"""Tests for FTS5 integrity checks and sync triggers."""

from brainkm.db.connection import connect
from brainkm.db.integrity import check_fts_integrity
from tests.conftest import insert_node


def test_fts_sync_and_integrity_check(brain_db) -> None:
    conn = connect(brain_db)
    try:
        insert_node(
            conn,
            node_id="n-auth",
            subtype="decision",
            title="Use JWT for API auth",
            content="Access tokens expire after 15 minutes",
        )
        conn.commit()

        row = conn.execute(
            "SELECT COUNT(*) FROM nodes_fts WHERE nodes_fts MATCH 'JWT'"
        ).fetchone()[0]
        assert row == 1

        issues = check_fts_integrity(conn)
        assert issues == {}
    finally:
        conn.close()
