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
# Cap document text for CE/cosine so rerank stays cheap.
_DOC_CHAR_LIMIT = 512


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
    """Clear loaded CE state (tests + post-download reload)."""
    global _CE_SESSION, _CE_TOKENIZER, _CE_FAILED, _CE_INPUT_NAMES, _CE_NP
    _CE_SESSION = None
    _CE_TOKENIZER = None
    _CE_FAILED = False
    _CE_INPUT_NAMES = []
    _CE_NP = None


def _document_text(node: RankedNode) -> str:
    """Match write-time embedding text: title + content (truncated)."""
    body = (node.content or "").strip()
    if body:
        text = f"{node.title}\n{body}"
    else:
        text = node.title or ""
    return text[:_DOC_CHAR_LIMIT]


def _ce_score(query: str, document: str) -> float:
    if not _load_cross_encoder():
        return 0.0
    assert _CE_TOKENIZER is not None and _CE_SESSION is not None and _CE_NP is not None
    np = _CE_NP
    # True pair encoding — HuggingFace tokenizers expect encode(query, document).
    try:
        encoded = _CE_TOKENIZER.encode(query, document)
    except TypeError:
        # Older/single-arg tokenizers: fall back to concatenated pair text.
        encoded = _CE_TOKENIZER.encode(f"{query} [SEP] {document}")
    ids = np.array([encoded.ids], dtype=np.int64)
    mask = np.array([encoded.attention_mask], dtype=np.int64)
    feeds: dict[str, object] = {}
    for name in _CE_INPUT_NAMES:
        lower = name.lower()
        if "token_type" in lower or "type_id" in lower:
            # Prefer tokenizer type ids when present (true pair segments).
            type_ids = getattr(encoded, "type_ids", None)
            if type_ids is not None:
                feeds[name] = np.array([type_ids], dtype=np.int64)
            else:
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


def _rescored(node: RankedNode, new_score: float) -> RankedNode:
    return RankedNode(
        node_id=node.node_id,
        activation=node.activation,
        score=new_score,
        kind=node.kind,
        subtype=node.subtype,
        title=node.title,
        path=node.path,
        relationship=node.relationship,
        via=node.via,
        content=node.content,
        updated_at=node.updated_at,
    )


def _cosine_rerank(query: str, nodes: list[RankedNode], top_n: int) -> list[RankedNode]:
    embedder = get_embedder(prefer_onnx=True)
    qvec = embedder.embed(query)
    head = nodes[:top_n]
    tail = nodes[top_n:]
    rescored: list[RankedNode] = []
    for node in head:
        dvec = embedder.embed(_document_text(node))
        sim = cosine_similarity(qvec, dvec)
        new_score = float(node.score) * 0.6 + max(0.0, sim) * 0.4 * max(float(node.score), 1.0)
        rescored.append(_rescored(node, new_score))
    rescored.sort(key=lambda item: item.score, reverse=True)
    return rescored + tail


def _ce_rerank(query: str, nodes: list[RankedNode], top_n: int) -> list[RankedNode]:
    head = nodes[:top_n]
    tail = nodes[top_n:]
    rescored: list[RankedNode] = []
    for node in head:
        ce = _ce_score(query, _document_text(node))
        new_score = float(node.score) * 0.5 + ce * 0.5 * max(float(node.score), 1.0)
        rescored.append(_rescored(node, new_score))
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
