"""Tests for FTS seeding and 2-hop BFS traversal."""

from brainkm.db.connection import connect
from brainkm.models.brain_config import GraphConfig, RecallConfig
from brainkm.services.search import recall_with_bfs, traverse, type_multiplier
from tests.conftest import insert_edge, insert_node


def test_type_multiplier_prefers_decisions() -> None:
    assert type_multiplier("memory", "decision") > type_multiplier("memory", "fact")


def test_recall_with_bfs_spreads_one_hop(brain_db) -> None:
    conn = connect(brain_db)
    try:
        insert_node(
            conn,
            node_id="seed",
            subtype="fact",
            title="auth module",
            content="authentication entrypoint",
        )
        insert_node(
            conn,
            node_id="neighbor",
            subtype="decision",
            title="payments coupling",
            content="payments imports auth",
        )
        insert_edge(conn, edge_id="e1", from_id="seed", to_id="neighbor", weight=0.9)
        conn.commit()

        result = recall_with_bfs(
            conn,
            "authentication",
            graph=GraphConfig(max_bfs_fanout_per_hop=10, max_activation_nodes=50),
            recall=RecallConfig(abstain_on_low_confidence=False),
        )
        ids = {node.node_id for node in result.nodes}
        assert "seed" in ids
        assert "neighbor" in ids
        assert result.nodes[0].score >= result.nodes[-1].score
    finally:
        conn.close()


def test_traverse_resolves_path_and_relationship(brain_db) -> None:
    conn = connect(brain_db)
    try:
        insert_node(
            conn,
            node_id="file-a",
            kind="code",
            subtype="file",
            title="auth.ts",
            path="src/auth.ts",
        )
        insert_node(
            conn,
            node_id="file-b",
            kind="code",
            subtype="file",
            title="payments.ts",
            path="src/payments.ts",
        )
        insert_edge(
            conn,
            edge_id="e2",
            from_id="file-a",
            to_id="file-b",
            relationship="imports",
            weight=1.0,
        )
        conn.commit()

        result = traverse(
            conn,
            "src/auth.ts",
            to_ref="src/payments.ts",
            max_hops=2,
            relationship="imports",
            direction="out",
        )
        assert result.resolved_id == "file-a"
        assert result.hint is None
        assert len(result.nodes) == 1
        assert result.nodes[0].node_id == "file-b"
        assert result.nodes[0].relationship == "imports"
        assert result.nodes[0].via == "file-a"
        assert result.hops_explored >= 1
    finally:
        conn.close()


def test_traverse_unresolved_hint(brain_db) -> None:
    conn = connect(brain_db)
    try:
        result = traverse(conn, "definitely-missing-node-xyz")
        assert result.nodes == []
        assert result.resolved_id is None
        assert result.hint is not None
    finally:
        conn.close()
