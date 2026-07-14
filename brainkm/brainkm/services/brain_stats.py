"""Brain health / stats for MCP `brain_stats` tool."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from brainkm.models.brain_config import BrainConfig
from brainkm.models.schemas import BrainStatsResponse
from brainkm.services.abstention_calibrate import load_calibration
from brainkm.services.channel_health import graph_available, graph_counts
from brainkm.services.review import list_pending
from brainkm.services.session_activity import ANON_SESSION_ID


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

    mcp_7d, mcp_30d, abstention_rate = _mcp_usage_stats(conn)
    dead_count = _dead_neuron_count(conn)

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
        mcp_calls_by_tool=mcp_7d,
        mcp_calls_30d=mcp_30d,
        abstention_rate_7d=abstention_rate,
        dead_neuron_count=dead_count,
    )


def _cutoff_iso(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _base_tool_name(tool_name: str | None) -> str:
    if not tool_name:
        return "unknown"
    return tool_name.split(":", 1)[0]


def _mcp_usage_stats(
    conn: sqlite3.Connection,
) -> tuple[dict[str, int], int, float | None]:
    """Return (calls_by_tool_7d, total_30d, abstention_rate_7d)."""
    try:
        cutoff_7 = _cutoff_iso(7)
        cutoff_30 = _cutoff_iso(30)
        rows_7 = conn.execute(
            """
            SELECT tool_name, source, COUNT(*) AS n
            FROM session_activity
            WHERE kind = 'tool_use'
              AND source IN ('mcp', 'mcp_abstained')
              AND created_at >= ?
            GROUP BY tool_name, source
            """,
            (cutoff_7,),
        ).fetchall()
        row_30 = conn.execute(
            """
            SELECT COUNT(*) FROM session_activity
            WHERE kind = 'tool_use'
              AND source IN ('mcp', 'mcp_abstained')
              AND created_at >= ?
            """,
            (cutoff_30,),
        ).fetchone()
    except sqlite3.OperationalError:
        return {}, 0, None

    by_tool: dict[str, int] = {}
    recall_total = 0
    recall_abstained = 0
    for tool_name, source, n in rows_7:
        base = _base_tool_name(tool_name)
        by_tool[base] = by_tool.get(base, 0) + int(n)
        if base == "recall":
            recall_total += int(n)
            if source == "mcp_abstained":
                recall_abstained += int(n)

    total_30 = int(row_30[0]) if row_30 else 0
    rate = (recall_abstained / recall_total) if recall_total else None
    return by_tool, total_30, rate


def _dead_neuron_count(conn: sqlite3.Connection) -> int:
    """Memory neurons with use_count=0 and no pending (unflushed) hits."""
    try:
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM nodes n
            WHERE n.valid_until IS NULL
              AND n.kind = 'memory'
              AND n.use_count = 0
              AND NOT EXISTS (
                SELECT 1 FROM session_activity sa
                WHERE sa.kind = 'neuron_hit'
                  AND sa.node_id = n.id
                  AND sa.session_id != ?
              )
            """,
            (ANON_SESSION_ID,),
        ).fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row[0]) if row else 0
