"""Rerank: CE when available, cosine fallback otherwise."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from brainkm.services.rerank import (
    _ce_score,
    _document_text,
    reset_cross_encoder_cache,
    rerank_nodes,
)
from brainkm.services.search import RankedNode


def _nodes() -> list[RankedNode]:
    return [
        RankedNode(
            node_id="a",
            activation=1.0,
            score=10.0,
            kind="memory",
            subtype="fact",
            title="JWT renewal",
            path=None,
            relationship=None,
            via=None,
            content="Prefer JWT refresh tokens for API auth renewal failures.",
        ),
        RankedNode(
            node_id="b",
            activation=0.5,
            score=8.0,
            kind="memory",
            subtype="fact",
            title="cookie banner copy",
            path=None,
            relationship=None,
            via=None,
            content="Marketing prefers a soft cookie consent banner.",
        ),
    ]


def test_document_text_includes_content() -> None:
    node = _nodes()[0]
    text = _document_text(node)
    assert "JWT renewal" in text
    assert "refresh tokens" in text


def test_rerank_disabled_passthrough() -> None:
    nodes = _nodes()
    out = rerank_nodes("auth token", nodes, enabled=False)
    assert out == nodes


def test_rerank_cosine_fallback_orders_relevant_first() -> None:
    reset_cross_encoder_cache()
    with patch("brainkm.services.rerank._load_cross_encoder", return_value=False):
        out = rerank_nodes("JWT auth token refresh", _nodes(), enabled=True)
    assert len(out) == 2
    assert out[0].node_id == "a"
    assert out[0].score >= out[1].score


def test_rerank_uses_ce_when_loaded() -> None:
    reset_cross_encoder_cache()
    with (
        patch("brainkm.services.rerank._load_cross_encoder", return_value=True),
        patch("brainkm.services.rerank._ce_score", side_effect=[0.9, 0.1]),
    ):
        out = rerank_nodes("query", _nodes(), enabled=True)
    assert out[0].node_id == "a"


def test_ce_score_uses_pair_encode() -> None:
    """Tokenizer.encode must be called with (query, document), not a joined string."""
    reset_cross_encoder_cache()
    import numpy as np

    tok = MagicMock()
    enc = MagicMock()
    enc.ids = [1, 2, 3]
    enc.attention_mask = [1, 1, 1]
    enc.type_ids = [0, 0, 1]
    tok.encode.return_value = enc
    session = MagicMock()
    session.run.return_value = [np.array([[2.0]])]

    with patch("brainkm.services.rerank._load_cross_encoder", return_value=True):
        import brainkm.services.rerank as rerank_mod

        rerank_mod._CE_TOKENIZER = tok
        rerank_mod._CE_SESSION = session
        rerank_mod._CE_INPUT_NAMES = ["input_ids", "attention_mask", "token_type_ids"]
        rerank_mod._CE_NP = np
        score = _ce_score("jwt auth", "token refresh doc")
    tok.encode.assert_called_once_with("jwt auth", "token refresh doc")
    assert 0.0 < score <= 1.0
    reset_cross_encoder_cache()
