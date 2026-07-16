"""Rerank: CE when available, cosine fallback otherwise."""

from __future__ import annotations

from unittest.mock import patch

from brainkm.services.rerank import reset_cross_encoder_cache, rerank_nodes
from brainkm.services.search import RankedNode


def _nodes() -> list[RankedNode]:
    return [
        RankedNode(
            node_id="a",
            activation=1.0,
            score=10.0,
            kind="memory",
            subtype="fact",
            title="JWT renewal failure",
            path=None,
            relationship=None,
            via=None,
        ),
        RankedNode(
            node_id="b",
            activation=0.5,
            score=8.0,
            kind="memory",
            subtype="fact",
            title="unrelated cookie policy",
            path=None,
            relationship=None,
            via=None,
        ),
    ]


def test_rerank_disabled_passthrough() -> None:
    nodes = _nodes()
    out = rerank_nodes("auth token", nodes, enabled=False)
    assert out == nodes


def test_rerank_cosine_fallback_when_no_ce() -> None:
    reset_cross_encoder_cache()
    with patch("brainkm.services.rerank._load_cross_encoder", return_value=False):
        out = rerank_nodes("JWT auth token refresh", _nodes(), enabled=True)
    assert len(out) == 2
    assert {n.node_id for n in out} == {"a", "b"}


def test_rerank_uses_ce_when_loaded() -> None:
    reset_cross_encoder_cache()
    with (
        patch("brainkm.services.rerank._load_cross_encoder", return_value=True),
        patch("brainkm.services.rerank._ce_score", side_effect=[0.9, 0.1]),
    ):
        out = rerank_nodes("query", _nodes(), enabled=True)
    assert out[0].node_id == "a"
