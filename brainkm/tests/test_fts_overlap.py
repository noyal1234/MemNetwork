"""Tests for FTS query-token overlap filtering."""

from __future__ import annotations

from brainkm.db.connection import connect
from brainkm.db.migrate import migrate
from brainkm.services.search import (
    count_token_overlap,
    filter_fts_hits_by_overlap,
    fts_search_nodes,
    query_tokens,
)
from tests.conftest import insert_node


def test_query_tokens_lowercase() -> None:
    assert query_tokens("GPU Machine Learning") == ["gpu", "machine", "learning"]


def test_count_token_overlap_word_boundary() -> None:
    assert count_token_overlap(["learning"], "Co-activation learning edges") == 1
    assert count_token_overlap(["learning"], "Co-activation edges") == 0


def test_filter_fts_drops_single_token_collision(brain_db) -> None:
    conn = connect(brain_db)
    try:
        insert_node(
            conn,
            node_id="theme",
            subtype="fact",
            title="Co-activation learning",
            content="co_activated edges increment when neurons appear together",
        )
        insert_node(
            conn,
            node_id="noise",
            subtype="fact",
            title="GPU cluster training",
            content="Machine learning training uses eight A100 GPUs",
        )
        conn.commit()
        hits = fts_search_nodes(conn, "machine learning gpu cluster training", limit=10)
        filtered = filter_fts_hits_by_overlap(conn, hits, "machine learning gpu cluster training")
        ids = {node_id for node_id, _ in filtered}
        assert "noise" in ids
        assert "theme" not in ids
    finally:
        conn.close()


def test_filter_skipped_for_single_token_query(tmp_path) -> None:
    db_path = tmp_path / ".brain" / "brain.db"
    migrate(db_path=db_path, run_integrity_check=False)
    conn = connect(db_path)
    try:
        insert_node(
            conn,
            node_id="a",
            subtype="fact",
            title="auth module",
            content="authentication",
        )
        conn.commit()
        hits = fts_search_nodes(conn, "auth", limit=5)
        assert hits
    finally:
        conn.close()
