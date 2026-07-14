"""Channel health flags — route-don't-fuse fallback when graph is unavailable."""

from __future__ import annotations

import sqlite3


def graph_available(conn: sqlite3.Connection) -> bool:
    """True when at least one Graphify import completed successfully."""
    row = conn.execute(
        """
        SELECT 1 FROM graph_import_runs
        WHERE status = 'completed'
        LIMIT 1
        """
    ).fetchone()
    return row is not None


def latest_graph_import_status(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        """
        SELECT status FROM graph_import_runs
        ORDER BY started_at DESC
        LIMIT 1
        """
    ).fetchone()
    return str(row[0]) if row else None


def graph_counts(conn: sqlite3.Connection) -> tuple[int, int]:
    """Return (code_node_count, edge_count) for SessionStart advertising."""
    nodes = conn.execute(
        """
        SELECT COUNT(*) FROM nodes
        WHERE kind = 'code' AND valid_until IS NULL
        """
    ).fetchone()[0]
    edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    return int(nodes), int(edges)
