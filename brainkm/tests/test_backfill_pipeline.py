"""Backfill + linking pipeline tests for about_* and supersedes edges."""

from __future__ import annotations

from pathlib import Path

from brainkm.db.connection import connect
from brainkm.db.migrate import migrate
from brainkm.services.backfill import backfill_neuron_links, backfill_supersedes
from brainkm.services.memory import create_neuron, remember_neuron
from brainkm.services.neuron_index import index_neuron_links
from tests.conftest import insert_node


def _brain(tmp_path: Path):
    db = tmp_path / ".brain" / "brain.db"
    migrate(db_path=db, run_integrity_check=True)
    return connect(db)


def test_backfill_links_adds_about_file(tmp_path: Path) -> None:
    conn = _brain(tmp_path)
    try:
        insert_node(
            conn,
            node_id="code1",
            kind="code",
            subtype="file",
            title="dispatch.py",
            path="brainkm/tools/dispatch.py",
        )
        mem = remember_neuron(
            conn,
            title="Dispatch stays thin",
            content="Handlers in brainkm/tools/dispatch.py must call services only.",
            subtype="decision",
            source="test",
        )
        conn.commit()
        # Simulate historical miss: no edges yet
        before = conn.execute(
            "SELECT COUNT(*) FROM edges WHERE relationship = 'about_file'"
        ).fetchone()[0]
        assert before == 0
        result = backfill_neuron_links(conn)
        conn.commit()
        assert result.edges_added >= 1
        edge = conn.execute(
            """
            SELECT 1 FROM edges
            WHERE from_id = ? AND to_id = ? AND relationship = 'about_file'
            """,
            (mem.id, "code1"),
        ).fetchone()
        assert edge is not None
    finally:
        conn.close()


def test_backfill_supersedes_chains_decisions(tmp_path: Path) -> None:
    conn = _brain(tmp_path)
    try:
        older = remember_neuron(
            conn,
            title="Auth transport: sessions",
            content="Use server sessions",
            subtype="decision",
            source="test",
        )
        newer = remember_neuron(
            conn,
            title="Auth transport: JWT",
            content="Use JWT instead of sessions",
            subtype="decision",
            source="test",
        )
        conn.commit()
        result = backfill_supersedes(conn, min_token_overlap=0.3)
        conn.commit()
        assert result.edges_added >= 1
        edge = conn.execute(
            """
            SELECT 1 FROM edges
            WHERE from_id = ? AND to_id = ? AND relationship = 'supersedes'
            """,
            (newer.id, older.id),
        ).fetchone()
        assert edge is not None
        # Idempotent
        again = backfill_supersedes(conn, min_token_overlap=0.3)
        assert again.edges_added == 0
    finally:
        conn.close()


def test_shortened_path_links_to_full_code_path(tmp_path: Path) -> None:
    conn = _brain(tmp_path)
    try:
        code = create_neuron(
            conn,
            title="graphify_watch.py",
            content="",
            kind="code",
            subtype="file",
            path="brainkm/brainkm/services/graphify_watch.py",
            source="test",
        )
        mem = remember_neuron(
            conn,
            title="Filesystem watch",
            content="Enable watch in brainkm/services/graphify_watch.py",
            subtype="fact",
            source="test",
        )
        linked = index_neuron_links(
            conn,
            mem.id,
            title=mem.title,
            content=mem.content or "",
            kind="memory",
        )
        assert code.id in linked
    finally:
        conn.close()
