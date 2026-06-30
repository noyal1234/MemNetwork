"""Atomic Graphify graph.json import into SQLite nodes/edges."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from brainkm.adapters.graphify import infer_code_subtype, load_graph_json, resolve_graph_json_path
from brainkm.db.checkpoint import wal_checkpoint
from brainkm.db.connection import connect
from brainkm.db.migrate import migrate
from brainkm.db.paths import brain_db_path
from brainkm.logging_config import get_logger
from brainkm.models.brain_config import BrainConfig
from brainkm.models.graphify import GraphImportResult, ParsedGraphifyGraph
from brainkm.services.audit import utc_now_iso
from brainkm.services.config_loader import load_brain_config
from brainkm.services.memory import new_ulid, token_count

logger = get_logger("services.graph_import")

_MAX_RETRIES = 5
_BASE_DELAY_SECONDS = 0.05

T = TypeVar("T")


def _with_busy_retry(fn: Callable[[], T]) -> T:
    for attempt in range(_MAX_RETRIES):
        try:
            return fn()
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if "locked" in message and attempt < _MAX_RETRIES - 1:
                delay = _BASE_DELAY_SECONDS * (2**attempt)
                logger.debug("graph import SQLITE_BUSY retry %d in %.3fs", attempt + 1, delay)
                time.sleep(delay)
                continue
            raise
    raise RuntimeError("unreachable")


def _edge_id(from_id: str, relation: str, to_id: str) -> str:
    return f"e:{from_id}:{relation}:{to_id}"


def _start_import_run(conn: sqlite3.Connection, *, run_id: str, started_at: str) -> None:
    conn.execute(
        """
        INSERT INTO graph_import_runs (id, started_at, status, node_count, edge_count)
        VALUES (?, ?, 'running', 0, 0)
        """,
        (run_id, started_at),
    )


def _finish_import_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    status: str,
    node_count: int,
    edge_count: int,
    completed_at: str,
) -> None:
    conn.execute(
        """
        UPDATE graph_import_runs
        SET status = ?, node_count = ?, edge_count = ?, completed_at = ?
        WHERE id = ?
        """,
        (status, node_count, edge_count, completed_at, run_id),
    )


def _purge_code_graph(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        DELETE FROM edges
        WHERE from_id IN (SELECT id FROM nodes WHERE kind = 'code')
           OR to_id IN (SELECT id FROM nodes WHERE kind = 'code')
        """
    )
    conn.execute("DELETE FROM nodes WHERE kind = 'code'")


def count_code_nodes(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) FROM nodes WHERE kind = 'code'").fetchone()
    return int(row[0]) if row else 0


def _insert_code_graph(conn: sqlite3.Connection, graph: ParsedGraphifyGraph) -> tuple[int, int]:
    now = utc_now_iso()
    node_rows: list[tuple[object, ...]] = []

    for node in graph.nodes:
        subtype = infer_code_subtype(node.label, node.graph_id)
        body_parts = []
        if node.source_location:
            body_parts.append(node.source_location)
        if node.extra:
            body_parts.append(json.dumps(node.extra, sort_keys=True))
        content = " | ".join(body_parts) if body_parts else None
        title = node.label
        tokens = token_count(f"{title}\n{content or ''}")

        node_rows.append(
            (
                node.graph_id,
                "code",
                subtype,
                title,
                content,
                node.source_file,
                json.dumps(["graphify", subtype], separators=(",", ":")),
                "graphify:import",
                1.0,
                tokens,
                now,
                now,
                now,
            )
        )

    conn.executemany(
        """
        INSERT INTO nodes (
          id, kind, subtype, title, content, path, tags, source,
          confidence, token_count, ingested_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        node_rows,
    )

    edge_rows: list[tuple[object, ...]] = []
    for link in graph.links:
        edge_rows.append(
            (
                _edge_id(link.source, link.relation, link.target),
                link.source,
                link.target,
                link.relation,
                link.weight,
                now,
                now,
            )
        )

    conn.executemany(
        """
        INSERT INTO edges (id, from_id, to_id, relationship, weight, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        edge_rows,
    )
    return len(node_rows), len(edge_rows)


def import_graph_json(
    graph_path: Path,
    *,
    project_dir: Path | None = None,
    config: BrainConfig | None = None,
    db_path: Path | None = None,
    code_only: bool | None = None,
) -> GraphImportResult:
    """Import Graphify graph.json into brain.db in a single transaction."""
    return _with_busy_retry(
        lambda: _import_graph_json_once(
            graph_path,
            project_dir=project_dir,
            config=config,
            db_path=db_path,
            code_only=code_only,
        )
    )


def _import_graph_json_once(
    graph_path: Path,
    *,
    project_dir: Path | None = None,
    config: BrainConfig | None = None,
    db_path: Path | None = None,
    code_only: bool | None = None,
) -> GraphImportResult:
    cfg = config or load_brain_config(project_dir)
    resolved_code_only = cfg.graphify.code_only if code_only is None else code_only
    parsed = load_graph_json(graph_path, code_only=resolved_code_only)

    resolved_db = db_path if db_path is not None else brain_db_path(project_dir)
    migrate(db_path=resolved_db, run_integrity_check=False)

    run_id = new_ulid()
    started_at = utc_now_iso()
    conn = connect(resolved_db)

    try:
        if len(parsed.nodes) == 0:
            existing_code = count_code_nodes(conn)
            if existing_code > 0:
                completed_at = utc_now_iso()
                _start_import_run(conn, run_id=run_id, started_at=started_at)
                _finish_import_run(
                    conn,
                    run_id=run_id,
                    status="skipped_empty",
                    node_count=0,
                    edge_count=0,
                    completed_at=completed_at,
                )
                conn.commit()
                logger.warning(
                    "Graph import refused: 0 code nodes after filter; "
                    "preserving %d existing code nodes",
                    existing_code,
                )
                return GraphImportResult(
                    run_id=run_id,
                    status="skipped_empty",
                    node_count=0,
                    edge_count=0,
                    skipped_non_code_nodes=0,
                    skipped_edges=0,
                    graph_path=str(graph_path),
                )

        _start_import_run(conn, run_id=run_id, started_at=started_at)
        conn.commit()

        conn.execute("BEGIN IMMEDIATE")
        _purge_code_graph(conn)
        node_count, edge_count = _insert_code_graph(conn, parsed)
        completed_at = utc_now_iso()
        _finish_import_run(
            conn,
            run_id=run_id,
            status="completed",
            node_count=node_count,
            edge_count=edge_count,
            completed_at=completed_at,
        )
        conn.commit()

        checkpoint = wal_checkpoint(conn)
        if not checkpoint.ok:
            logger.warning("wal_checkpoint after graph import did not fully flush")

        logger.info(
            "Graph import completed run_id=%s nodes=%d edges=%d",
            run_id,
            node_count,
            edge_count,
        )
        return GraphImportResult(
            run_id=run_id,
            status="completed",
            node_count=node_count,
            edge_count=edge_count,
            skipped_non_code_nodes=0,
            skipped_edges=0,
            graph_path=str(graph_path),
        )
    except Exception:
        conn.rollback()
        failed_at = utc_now_iso()
        try:
            _finish_import_run(
                conn,
                run_id=run_id,
                status="failed",
                node_count=0,
                edge_count=0,
                completed_at=failed_at,
            )
            conn.commit()
        except Exception:
            conn.rollback()
        raise
    finally:
        conn.close()


def import_project_graph(
    *,
    project_dir: Path | None = None,
    config: BrainConfig | None = None,
    db_path: Path | None = None,
    graph_path: Path | None = None,
) -> GraphImportResult:
    """Import graph.json from configured project path."""
    cfg = config or load_brain_config(project_dir)
    if not cfg.graphify.enabled:
        return GraphImportResult(
            run_id="",
            status="skipped",
            node_count=0,
            edge_count=0,
            skipped_non_code_nodes=0,
            skipped_edges=0,
            graph_path="",
        )

    resolved_path = graph_path or resolve_graph_json_path(
        project_dir,
        graph_json=cfg.graphify.graph_json,
    )
    if not resolved_path.is_file():
        msg = f"graph.json not found: {resolved_path}"
        raise FileNotFoundError(msg)

    return import_graph_json(
        resolved_path,
        project_dir=project_dir,
        config=cfg,
        db_path=db_path,
    )
