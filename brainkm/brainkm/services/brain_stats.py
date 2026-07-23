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
    session_id: str | None = None,
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
    calibrated = bool(calibration and calibration.corpus_bm25_threshold is not None)

    mcp_7d, mcp_30d, abstention_rate = _mcp_usage_stats(conn)
    dead_count = _dead_neuron_count(conn)
    hygiene_hint = None
    if dead_count >= 25:
        hygiene_hint = (
            f"{dead_count} unused active neurons — run `brainkm hygiene` "
            "(or enable capture.auto_hygiene) to soft-archive noise"
        )

    session_fields: dict = {}
    if session_id:
        session_fields = _session_scoped_stats(conn, session_id)

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
        hygiene_hint=hygiene_hint,
        outbound_gate_7d=_outbound_gate_stats(conn),
        traverse_abstain_7d=_traverse_abstain_stats(conn),
        **session_fields,
    )


def _session_scoped_stats(conn: sqlite3.Connection, session_id: str) -> dict:
    """Per-session telemetry for brain_stats when session_id is provided."""
    calls_by_tool: dict[str, int] = {}
    neuron_hits = 0
    try:
        rows = conn.execute(
            """
            SELECT tool_name, source, COUNT(*) AS n
            FROM session_activity
            WHERE kind = 'tool_use'
              AND session_id = ?
              AND source IN ('mcp', 'mcp_abstained')
            GROUP BY tool_name, source
            """,
            (session_id,),
        ).fetchall()
        for tool_name, _source, n in rows:
            base = _base_tool_name(tool_name)
            calls_by_tool[base] = calls_by_tool.get(base, 0) + int(n)

        hit_row = conn.execute(
            """
            SELECT COUNT(*) FROM session_activity
            WHERE kind = 'neuron_hit' AND session_id = ?
            """,
            (session_id,),
        ).fetchone()
        neuron_hits = int(hit_row[0]) if hit_row else 0
    except sqlite3.OperationalError:
        pass

    injection_tokens: int | None = None
    try:
        snap = conn.execute(
            """
            SELECT token_count FROM session_snapshots
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
        if snap is not None:
            injection_tokens = int(snap[0] or 0)
    except sqlite3.OperationalError:
        pass

    distill_mode: str | None = None
    neuron_count: int | None = None
    try:
        ingested = conn.execute(
            """
            SELECT distill_mode, neuron_count FROM ingested_sessions
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
        if ingested is not None:
            distill_mode = str(ingested[0]) if ingested[0] is not None else None
            neuron_count = int(ingested[1]) if ingested[1] is not None else None
    except sqlite3.OperationalError:
        pass

    return {
        "session_id": session_id,
        "session_mcp_calls_by_tool": calls_by_tool,
        "session_neuron_hits": neuron_hits,
        "session_injection_tokens": injection_tokens,
        "session_distill_mode": distill_mode,
        "session_neuron_count": neuron_count,
    }


def _cutoff_iso(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _base_tool_name(tool_name: str | None) -> str:
    if not tool_name:
        return "unknown"
    return tool_name.split(":", 1)[0]


def _outbound_gate_stats(conn: sqlite3.Connection) -> dict[str, int]:
    """Aggregate outbound_gate fires (block/strip/noise) over 7 days."""
    out: dict[str, int] = {"block": 0, "strip": 0, "noise": 0}
    try:
        rows = conn.execute(
            """
            SELECT tool_name FROM session_activity
            WHERE kind = 'outbound_gate'
              AND created_at >= ?
            """,
            (_cutoff_iso(7),),
        ).fetchall()
    except sqlite3.OperationalError:
        return out
    for (tool_name,) in rows:
        if not tool_name:
            continue
        # Encoded as reason:count
        reason, _, count_s = str(tool_name).partition(":")
        if reason not in out:
            continue
        try:
            out[reason] += max(1, int(count_s or "1"))
        except ValueError:
            out[reason] += 1
    return out


def _traverse_abstain_stats(conn: sqlite3.Connection) -> dict[str, int]:
    """Count traverse abstentions by unresolved|ambiguous over 7 days."""
    out: dict[str, int] = {"unresolved": 0, "ambiguous": 0}
    try:
        rows = conn.execute(
            """
            SELECT tool_name FROM session_activity
            WHERE kind = 'tool_use'
              AND source = 'mcp_abstained'
              AND tool_name LIKE 'traverse:%'
              AND created_at >= ?
            """,
            (_cutoff_iso(7),),
        ).fetchall()
    except sqlite3.OperationalError:
        return out
    for (tool_name,) in rows:
        parts = str(tool_name or "").split(":")
        # traverse:ambiguous:0 or traverse:unresolved:0
        if len(parts) >= 2 and parts[1] in out:
            out[parts[1]] += 1
    return out


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
