"""Tests for recall abstention thresholds."""

from brainkm.db.connection import connect
from brainkm.models.brain_config import RecallConfig
from brainkm.services.abstention import should_abstain, should_abstain_for_query
from brainkm.services.search import recall_with_bfs
from tests.conftest import insert_node


def test_should_abstain_on_empty_scores() -> None:
    recall = RecallConfig()
    assert should_abstain([], recall) is True


def test_absolute_abstention_blocks_weak_match() -> None:
    recall = RecallConfig(abstain_mode="absolute", min_recall_score=5.0)
    assert should_abstain([-0.5], recall) is True
    assert should_abstain([-8.0], recall) is False


def test_percentile_abstention_uses_corpus_threshold() -> None:
    recall = RecallConfig(abstain_mode="percentile", abstain_percentile=0.25)
    assert should_abstain([-0.1], recall, corpus_threshold=-2.0) is True
    assert should_abstain([-5.0], recall, corpus_threshold=-2.0) is False


def test_recall_with_bfs_abstains_on_absolute_threshold(brain_db) -> None:
    conn = connect(brain_db)
    try:
        insert_node(
            conn,
            node_id="weak",
            title="misc note",
            content="unrelated content",
        )
        conn.commit()

        result = recall_with_bfs(
            conn,
            "zzzznonexistentterm",
            recall=RecallConfig(abstain_mode="absolute", min_recall_score=10.0),
        )
        assert result.nodes == []
    finally:
        conn.close()


def test_recall_with_bfs_returns_results_when_confident(brain_db) -> None:
    conn = connect(brain_db)
    try:
        insert_node(
            conn,
            node_id="auth",
            subtype="decision",
            title="JWT authentication policy",
            content="Use JWT access tokens with 15 minute expiry",
        )
        conn.commit()

        result = recall_with_bfs(
            conn,
            "JWT authentication",
            recall=RecallConfig(abstain_on_low_confidence=False),
        )
        assert len(result.nodes) == 1
        assert result.nodes[0].node_id == "auth"
    finally:
        conn.close()


def test_should_abstain_for_query_with_no_matches(brain_db) -> None:
    conn = connect(brain_db)
    try:
        abstained = should_abstain_for_query(
            conn,
            [],
            RecallConfig(),
        )
        assert abstained is True
    finally:
        conn.close()
