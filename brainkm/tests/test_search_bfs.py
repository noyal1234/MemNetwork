"""Tests for FTS seeding and 2-hop BFS traversal."""

from datetime import UTC, datetime

import pytest

from brainkm.db.connection import connect
from brainkm.models.brain_config import GraphConfig, RecallConfig
from brainkm.services.search import (
    _ActivationMeta,
    _decay_multiplier,
    rank_activated_nodes,
    recall_with_bfs,
    traverse,
    type_multiplier,
)
from tests.conftest import insert_edge, insert_node


def test_type_multiplier_prefers_decisions() -> None:
    assert type_multiplier("memory", "decision") > type_multiplier("memory", "fact")


def test_decay_multiplier_offset_independent(monkeypatch) -> None:
    """Same instant in UTC vs +05:30 must yield the same age (no naive tz stripping)."""
    import brainkm.services.search as search_mod

    fixed_now = datetime(2026, 7, 28, 12, 0, 0, tzinfo=UTC)

    class _FixedDateTime:
        @staticmethod
        def now(tz=None):  # noqa: ANN001
            assert tz is UTC
            return fixed_now

        fromisoformat = staticmethod(datetime.fromisoformat)
        strptime = staticmethod(datetime.strptime)

    monkeypatch.setattr(search_mod, "datetime", _FixedDateTime)

    utc = "2026-07-21T12:00:00+00:00"  # exactly 7 days before fixed_now
    ist = "2026-07-21T17:30:00+05:30"  # same instant
    half_life = 7.0
    a = _decay_multiplier(utc, 0, half_life_days=half_life)
    b = _decay_multiplier(ist, 0, half_life_days=half_life)
    assert a == b
    # 7-day age / 7-day half-life → recency 0.5; use_boost=1.0 → 0.35 + 0.65*0.5 = 0.675
    assert abs(a - 0.675) < 1e-9


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


def test_direct_match_outranks_co_activated_hub(brain_db) -> None:
    """A neuron that literally matches the query must beat a co_activated hub.

    Regression: score was activation * confidence * type_multiplier with no
    lexical term, so BM25 only chose seeds and PPR mass decided order. A
    'decision' (multiplier 2.0) reached purely via co_activated edges could
    outrank the 'error' neuron (1.5) written to answer that exact query.
    """
    conn = connect(brain_db)
    try:
        insert_node(
            conn,
            node_id="error-neuron",
            subtype="error",
            title="hooks silently skipped when pth file is hidden",
            content="UF_HIDDEN makes site.py skip the editable install",
        )
        insert_node(
            conn,
            node_id="hub-decision",
            subtype="decision",
            title="unrelated architecture choice",
            content="prefer bounded packs over file dumps",
        )
        conn.commit()

        # Equal activation isolates the type multiplier vs the new lexical term.
        activations = {
            "error-neuron": _ActivationMeta(activation=0.10, depth=0),
            "hub-decision": _ActivationMeta(
                activation=0.10, depth=1, via="error-neuron", relationship="co_activated"
            ),
        }
        cfg = RecallConfig()

        baseline = rank_activated_nodes(conn, activations, recall=cfg)
        assert baseline[0].node_id == "hub-decision", "precondition: hub wins without the fix"

        boosted = rank_activated_nodes(
            conn,
            activations,
            recall=cfg,
            direct_match_ids=frozenset({"error-neuron"}),
        )
        assert boosted[0].node_id == "error-neuron", [n.node_id for n in boosted]
    finally:
        conn.close()


def test_direct_match_boost_is_recall_only(brain_db) -> None:
    """traverse() passes no direct_match_ids, so structural ranking is unchanged."""
    conn = connect(brain_db)
    try:
        insert_node(conn, node_id="a", subtype="fact", title="alpha", content="x")
        insert_node(conn, node_id="b", subtype="fact", title="beta", content="y")
        conn.commit()
        activations = {
            "a": _ActivationMeta(activation=0.2, depth=0),
            "b": _ActivationMeta(activation=0.1, depth=1),
        }
        cfg = RecallConfig()
        without = rank_activated_nodes(conn, activations, recall=cfg)
        explicit_none = rank_activated_nodes(
            conn, activations, recall=cfg, direct_match_ids=None
        )
        assert [n.node_id for n in without] == [n.node_id for n in explicit_none]
        # Recency decay reads the wall clock, so scores differ in the last bits.
        for lhs, rhs in zip(without, explicit_none, strict=True):
            assert lhs.score == pytest.approx(rhs.score, rel=1e-6)
    finally:
        conn.close()
