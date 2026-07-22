"""Live DB recall — always fresh; never reads frozen injection snapshots."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from brainkm.models.brain_config import BrainConfig, GraphConfig, RecallConfig, SemanticConfig
from brainkm.services.recall_dedup import SessionChunkHit, deduped_session_chunks
from brainkm.services.search import RankedNode, recall_with_bfs


@dataclass(frozen=True)
class LiveRecallResult:
    query: str
    nodes: list[RankedNode]
    source: str
    abstained: bool
    session_chunks: tuple[SessionChunkHit, ...] = ()
    intent: str | None = None
    fts_bm25_by_id: dict[str, float] = field(default_factory=dict)


def recall_live(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 5,
    graph: GraphConfig | None = None,
    recall: RecallConfig | None = None,
    semantic: SemanticConfig | None = None,
    config: BrainConfig | None = None,
    fts_limit: int = 20,
    project_dir: Path | None = None,
    extra_seed_ids: list[str] | None = None,
) -> LiveRecallResult:
    """Query live brain.db — includes neurons written mid-session via remember."""
    if config is not None:
        graph = graph or config.graph
        recall = recall or config.recall
        semantic = semantic or config.semantic_config()
    recall_cfg = recall or RecallConfig()
    traversal = recall_with_bfs(
        conn,
        query,
        graph=graph,
        recall=recall_cfg,
        semantic=semantic,
        fts_limit=fts_limit,
        project_dir=project_dir,
        extra_seed_ids=extra_seed_ids,
    )
    nodes = traversal.nodes[:limit]
    # Skip supplemental transcript chunks when abstained or the pack is empty.
    if traversal.abstained or not nodes:
        supplemental: tuple[SessionChunkHit, ...] = ()
    else:
        neuron_ids = {ranked.node_id for ranked in nodes}
        supplemental = tuple(
            deduped_session_chunks(
                conn,
                query,
                neuron_ids,
                min_bm25_strength=recall_cfg.min_bm25_strength,
            )
        )
    return LiveRecallResult(
        query=query,
        nodes=nodes,
        source="live_db",
        abstained=traversal.abstained,
        session_chunks=supplemental,
        intent=traversal.intent,
        fts_bm25_by_id=dict(traversal.fts_bm25_by_id),
    )
