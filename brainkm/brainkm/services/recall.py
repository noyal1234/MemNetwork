"""Live DB recall — always fresh; never reads frozen injection snapshots."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
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
) -> LiveRecallResult:
    """Query live brain.db — includes neurons written mid-session via remember."""
    if config is not None:
        graph = graph or config.graph
        recall = recall or config.recall
        semantic = semantic or config.semantic_config()
    traversal = recall_with_bfs(
        conn,
        query,
        graph=graph,
        recall=recall,
        semantic=semantic,
        fts_limit=fts_limit,
        project_dir=project_dir,
    )
    neuron_ids = {ranked.node_id for ranked in traversal.nodes}
    supplemental = deduped_session_chunks(conn, query, neuron_ids)
    return LiveRecallResult(
        query=query,
        nodes=traversal.nodes[:limit],
        source="live_db",
        abstained=traversal.abstained,
        session_chunks=tuple(supplemental),
        intent=traversal.intent,
    )
