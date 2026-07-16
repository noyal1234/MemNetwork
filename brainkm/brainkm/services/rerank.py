"""Optional local reranker for top-N fused recall candidates."""

from __future__ import annotations

import math

from brainkm.adapters.embeddings import cosine_similarity, get_embedder
from brainkm.logging_config import get_logger
from brainkm.services.search import RankedNode

logger = get_logger("services.rerank")

_CE_SESSION = None
_CE_TOKENIZER = None
_CE_FAILED = False
_CE_INPUT_NAMES: list[str] = []
_CE_NP = None
MAX_SEQ_LEN = 128


def _load_cross_encoder() -> bool:
    global _CE_SESSION, _CE_TOKENIZER, _CE_FAILED, _CE_INPUT_NAMES, _CE_NP
    if _CE_SESSION is not None:
        return True
    if _CE_FAILED:
        return False
    try:
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer
    except ImportError:
        _CE_FAILED = True
        return False
    from brainkm.adapters.onnx_models import ensure_cross_encoder

    paths = ensure_cross_encoder(download=False)
    if paths is None:
        return False
    model_path, tok_path = paths
    try:
        _CE_TOKENIZER = Tokenizer.from_file(str(tok_path))
        _CE_TOKENIZER.enable_truncation(max_length=MAX_SEQ_LEN)
        _CE_TOKENIZER.enable_padding(length=MAX_SEQ_LEN)
        _CE_SESSION = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )
        _CE_INPUT_NAMES = [inp.name for inp in _CE_SESSION.get_inputs()]
        _CE_NP = np
    except Exception:  # noqa: BLE001
        logger.debug("cross-encoder load failed", exc_info=True)
        _CE_SESSION = None
        _CE_TOKENIZER = None
        _CE_FAILED = True
        return False
    return True


def cross_encoder_available() -> bool:
    from brainkm.adapters.onnx_models import cross_encoder_cached

    if not cross_encoder_cached():
        return False
    return _load_cross_encoder()


def reset_cross_encoder_cache() -> None:
    """Test helper — clear loaded CE state."""
    global _CE_SESSION, _CE_TOKENIZER, _CE_FAILED, _CE_INPUT_NAMES, _CE_NP
    _CE_SESSION = None
    _CE_TOKENIZER = None
    _CE_FAILED = False
    _CE_INPUT_NAMES = []
    _CE_NP = None


def _ce_score(query: str, document: str) -> float:
    if not _load_cross_encoder():
        return 0.0
    assert _CE_TOKENIZER is not None and _CE_SESSION is not None and _CE_NP is not None
    np = _CE_NP
    # Pair encoding: query [SEP] document when tokenizer supports; else concat.
    pair = f"{query} [SEP] {document}"
    encoded = _CE_TOKENIZER.encode(pair)
    ids = np.array([encoded.ids], dtype=np.int64)
    mask = np.array([encoded.attention_mask], dtype=np.int64)
    feeds: dict[str, object] = {}
    for name in _CE_INPUT_NAMES:
        lower = name.lower()
        if "token_type" in lower or "type_id" in lower:
            feeds[name] = np.zeros_like(ids)
        elif "mask" in lower:
            feeds[name] = mask
        else:
            feeds[name] = ids
    outputs = _CE_SESSION.run(None, feeds)
    logits = outputs[0]
    value = float(logits.reshape(-1)[0])
    # Squash to ~[0,1] for blending with FTS/PPR scores.
    return 1.0 / (1.0 + math.exp(max(-50.0, min(50.0, -value))))


def _cosine_rerank(query: str, nodes: list[RankedNode], top_n: int) -> list[RankedNode]:
    embedder = get_embedder(prefer_onnx=True)
    qvec = embedder.embed(query)
    head = nodes[:top_n]
    tail = nodes[top_n:]
    rescored: list[RankedNode] = []
    for node in head:
        doc = f"{node.title}"
        dvec = embedder.embed(doc)
        sim = cosine_similarity(qvec, dvec)
        new_score = float(node.score) * 0.6 + max(0.0, sim) * 0.4 * max(float(node.score), 1.0)
        rescored.append(
            RankedNode(
                node_id=node.node_id,
                activation=node.activation,
                score=new_score,
                kind=node.kind,
                subtype=node.subtype,
                title=node.title,
                path=node.path,
                relationship=node.relationship,
                via=node.via,
            )
        )
    rescored.sort(key=lambda item: item.score, reverse=True)
    return rescored + tail


def _ce_rerank(query: str, nodes: list[RankedNode], top_n: int) -> list[RankedNode]:
    head = nodes[:top_n]
    tail = nodes[top_n:]
    rescored: list[RankedNode] = []
    for node in head:
        doc = f"{node.title}"
        ce = _ce_score(query, doc)
        new_score = float(node.score) * 0.5 + ce * 0.5 * max(float(node.score), 1.0)
        rescored.append(
            RankedNode(
                node_id=node.node_id,
                activation=node.activation,
                score=new_score,
                kind=node.kind,
                subtype=node.subtype,
                title=node.title,
                path=node.path,
                relationship=node.relationship,
                via=node.via,
            )
        )
    rescored.sort(key=lambda item: item.score, reverse=True)
    return rescored + tail


def rerank_nodes(
    query: str,
    nodes: list[RankedNode],
    *,
    top_n: int = 20,
    enabled: bool = True,
) -> list[RankedNode]:
    """Rerank top-N with cross-encoder when cached; else cosine blend fallback.

    When disabled, returns nodes unchanged.
    """
    if not enabled or not nodes:
        return nodes
    if _load_cross_encoder():
        return _ce_rerank(query, nodes, top_n)
    return _cosine_rerank(query, nodes, top_n)
