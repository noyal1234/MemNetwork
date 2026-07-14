"""Repair brain.db — rebuild FTS5 from nodes table."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from brainkm.adapters.redaction import sanitize_for_storage
from brainkm.db.connection import connect
from brainkm.db.integrity import check_fts_integrity
from brainkm.db.migrate import migrate
from brainkm.db.paths import brain_db_path
from brainkm.logging_config import get_logger
from brainkm.services.memory import forget_neuron

logger = get_logger("services.repair")


@dataclass(frozen=True)
class RepairResult:
    fts_rows_rebuilt: int
    integrity_ok: bool
    secrets_archived: int = 0


def rebuild_fts5(conn: sqlite3.Connection) -> int:
    conn.execute("INSERT INTO nodes_fts(nodes_fts) VALUES('rebuild')")
    row = conn.execute("SELECT COUNT(*) FROM nodes_fts").fetchone()
    return int(row[0]) if row else 0


def rescan_neurons_for_secrets(conn: sqlite3.Connection) -> int:
    """Soft-archive active memory neurons that fail the current redaction policy.

    Earlier captures used create_neuron() and may have stored secrets; repair
    re-scans and forgets matches so they leave live recall.
    """
    rows = conn.execute(
        """
        SELECT id, title, content
        FROM nodes
        WHERE valid_until IS NULL
          AND kind IN ('memory', 'procedure', 'tool')
        """
    ).fetchall()
    archived = 0
    for row in rows:
        result = sanitize_for_storage(row["title"] or "", row["content"] or "")
        if not result.blocked:
            continue
        forget_neuron(conn, row["id"], reason=f"repair:redaction:{result.block_reason}")
        archived += 1
        logger.warning(
            "Archived neuron %s during repair redaction scan: %s",
            row["id"],
            result.block_reason,
        )
    return archived


def repair_brain(
    *,
    project_dir: Path | None = None,
    recalibrate_abstention: bool = True,
    reset_rolling_scores: bool = True,
    rescan_secrets: bool = True,
) -> RepairResult:
    migrate(project_dir=project_dir, run_integrity_check=False)
    conn = connect(brain_db_path(project_dir))
    secrets_archived = 0
    try:
        if rescan_secrets:
            secrets_archived = rescan_neurons_for_secrets(conn)
        count = rebuild_fts5(conn)
        conn.commit()
        issues = check_fts_integrity(conn)
        integrity_ok = not any(issues.values())
    finally:
        conn.close()

    if reset_rolling_scores:
        repair_rolling_scores(project_dir=project_dir)

    if recalibrate_abstention:
        from brainkm.services.abstention_calibrate import recalibrate_after_repair

        recalibrate_after_repair(project_dir)

    return RepairResult(
        fts_rows_rebuilt=count,
        integrity_ok=integrity_ok,
        secrets_archived=secrets_archived,
    )


def repair_rolling_scores(*, project_dir: Path | None = None) -> int:
    """Sanitize or remove polluted abstention rolling scores (e.g. after bench runs)."""
    from brainkm.services.abstention_calibrate import (
        _load_rolling_scores,
        rolling_scores_path,
    )

    path = rolling_scores_path(project_dir)
    if not path.is_file():
        return 0
    raw = path.read_text(encoding="utf-8")
    cleaned = _load_rolling_scores(path)
    if len(cleaned) < 10:
        path.unlink(missing_ok=True)
        return 0
    import json

    sanitized = json.dumps(cleaned)
    if sanitized != raw.strip():
        path.write_text(sanitized, encoding="utf-8")
    return len(cleaned)
