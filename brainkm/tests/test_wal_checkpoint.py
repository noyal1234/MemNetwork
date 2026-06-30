"""Tests for WAL checkpoint helpers."""

from brainkm.db.checkpoint import wal_checkpoint
from brainkm.db.connection import connect
from brainkm.db.migrate import migrate
from tests.conftest import insert_node


def test_wal_checkpoint_succeeds_after_write(brain_db) -> None:
    conn = connect(brain_db)
    try:
        insert_node(conn, node_id="n-checkpoint", title="checkpoint test")
        conn.commit()
        result = wal_checkpoint(conn)
        assert result.ok is True
        assert result.busy == 0
    finally:
        conn.close()


def test_wal_checkpoint_after_migrate(tmp_path) -> None:
    db_path = tmp_path / ".brain" / "brain.db"
    migrate(db_path=db_path, run_integrity_check=False)
    conn = connect(db_path)
    try:
        result = wal_checkpoint(conn)
        assert result.ok is True
    finally:
        conn.close()
