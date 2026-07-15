"""Optional local reranker for top-N fused recall candidates."""

from __future__ import annotations

from brainkm.adapters.embeddings import cosine_similarity, get_embedder
from brainkm.services.search import RankedNode


def rerank_nodes(
    query: str,
    nodes: list[RankedNode],
    *,
    top_n: int = 20,
    enabled: bool = True,
) -> list[RankedNode]:
    """Rerank by query–document embedding cosine; blend with existing score.

    No cross-encoder weights bundled yet — uses the same local embedder as T1.
    When disabled, returns nodes unchanged.
    """
    if not enabled or not nodes:
        return nodes
    embedder = get_embedder(prefer_onnx=True)
    qvec = embedder.embed(query)
    head = nodes[:top_n]
    tail = nodes[top_n:]
    rescored: list[RankedNode] = []
    for node in head:
        doc = f"{node.title}"
        dvec = embedder.embed(doc)
        sim = cosine_similarity(qvec, dvec)
        # Blend: keep graph/FTS signal while lifting semantic match.
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
