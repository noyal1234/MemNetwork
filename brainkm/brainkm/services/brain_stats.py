"""Brain health / stats for MCP `brain_stats` tool."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from brainkm.models.brain_config import BrainConfig
from brainkm.models.schemas import BrainStatsResponse
from brainkm.services.abstention_calibrate import load_calibration
from brainkm.services.channel_health import graph_available, graph_counts
from brainkm.services.review import list_pending


def collect_brain_stats(
    conn: sqlite3.Connection,
    *,
    config: BrainConfig,
    project_dir: Path | None = None,
) -> BrainStatsResponse:
    """Aggregate counts and graph freshness for agent/operator inspection."""
    kind_rows = conn.execute(
        """
        SELECT kind, COUNT(*) AS n
        FROM nodes
        WHERE valid_until IS NULL
        GROUP BY kind
        """
    ).fetchall()
    subtype_rows = conn.execute(
        """
        SELECT COALESCE(subtype, ''), COUNT(*) AS n
        FROM nodes
        WHERE valid_until IS NULL AND kind = 'memory'
        GROUP BY subtype
        """
    ).fetchall()

    code_nodes, edges = graph_counts(conn)
    available = graph_available(conn)

    last_import = conn.execute(
        """
        SELECT completed_at, started_at
        FROM graph_import_runs
        WHERE status = 'completed'
        ORDER BY COALESCE(completed_at, started_at) DESC
        LIMIT 1
        """
    ).fetchone()
    last_at = None
    if last_import is not None:
        last_at = last_import[0] or last_import[1]

    graph_stale: bool | None = None
    if project_dir is not None and config.graphify.enabled:
        from brainkm.services.graphify_sync import (
            _graph_json_path,
            graph_json_newer_than_import,
        )

        graph_path = _graph_json_path(project_dir, config)
        if graph_path.is_file():
            graph_stale = graph_json_newer_than_import(project_dir, config)
        elif available:
            graph_stale = False
        else:
            graph_stale = None

    review_size = 0
    if project_dir is not None:
        review_size = len(list_pending(project_dir))

    calibration = load_calibration(project_dir) if project_dir is not None else None
    calibrated = bool(
        calibration and calibration.corpus_bm25_threshold is not None
    )

    return BrainStatsResponse(
        neurons_by_kind={str(row[0]): int(row[1]) for row in kind_rows},
        neurons_by_subtype={str(row[0]) or "(none)": int(row[1]) for row in subtype_rows},
        graph_nodes=code_nodes,
        graph_edges=edges,
        graph_available=available,
        last_graph_import_at=str(last_at) if last_at else None,
        graph_stale=graph_stale,
        review_queue_size=review_size,
        abstention_mode=config.recall.abstain_mode,
        abstention_calibrated=calibrated,
    )
