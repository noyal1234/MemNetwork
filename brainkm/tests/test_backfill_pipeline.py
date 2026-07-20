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
            content="Use server sessions for API auth",
            subtype="decision",
            source="test",
        )
        newer = remember_neuron(
            conn,
            title="Auth transport: JWT",
            content="Use JWT instead of sessions for API auth",
            subtype="decision",
            source="test",
        )
        conn.commit()
        # Dry-run with conflict gate off still previews Jaccard pairs.
        preview = backfill_supersedes(
            conn, min_token_overlap=0.3, dry_run=True, require_conflict=False
        )
        assert preview.dry_run is True
        assert preview.pairs >= 1
        assert preview.edges_added == 0
        assert (
            conn.execute(
                "SELECT valid_until FROM nodes WHERE id = ?", (older.id,)
            ).fetchone()[0]
            is None
        )

        # Apply: conflict gate should allow "instead of" pair.
        result = backfill_supersedes(conn, min_token_overlap=0.3, require_conflict=True)
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
        again = backfill_supersedes(conn, min_token_overlap=0.3)
        assert again.edges_added == 0
    finally:
        conn.close()


def test_backfill_supersedes_skips_without_conflict_signal(tmp_path: Path) -> None:
    """Shared wording alone must not archive distinct active decisions."""
    conn = _brain(tmp_path)
    try:
        a = remember_neuron(
            conn,
            title="Token budget for packs",
            content="Keep context packs under 1500 tokens",
            subtype="decision",
            source="test",
        )
        b = remember_neuron(
            conn,
            title="Token budget for embeddings",
            content="Cap embedding batch size independently of pack budget",
            subtype="decision",
            source="test",
        )
        conn.commit()
        # Jaccard would match, but without a conflict/high-sim signal both stay.
        loose = backfill_supersedes(
            conn, min_token_overlap=0.3, dry_run=True, require_conflict=False
        )
        assert loose.pairs >= 1
        gated = backfill_supersedes(
            conn, min_token_overlap=0.3, require_conflict=True
        )
        conn.commit()
        assert gated.edges_added == 0
        active = conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE id IN (?, ?) AND valid_until IS NULL",
            (a.id, b.id),
        ).fetchone()[0]
        assert active == 2
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
