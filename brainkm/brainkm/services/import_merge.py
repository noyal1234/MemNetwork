"""Import exported neurons with merge policy — higher confidence wins."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from brainkm.adapters.redaction import RedactionBlockedError
from brainkm.db.connection import connect
from brainkm.db.migrate import migrate
from brainkm.db.paths import brain_db_path
from brainkm.logging_config import get_logger
from brainkm.services.memory import new_ulid, remember_neuron, supersede_neuron

logger = get_logger("services.import_merge")


@dataclass(frozen=True)
class ImportMergeResult:
    imported: int
    skipped: int
    conflicts: int


def _parse_export_records(data: list[dict]) -> list[dict]:
    return [item for item in data if isinstance(item, dict) and item.get("title")]


def _remember_import_neuron(
    conn: sqlite3.Connection,
    *,
    title: str,
    content: str,
    item: dict,
    confidence: float,
    node_id: str | None = None,
):
    return remember_neuron(
        conn,
        title=title,
        content=content,
        kind=str(item.get("kind", "memory")),
        subtype=item.get("subtype"),
        confidence=confidence,
        node_id=node_id or new_ulid(),
        source="import:merge",
    )


def import_neurons_merge(
    conn: sqlite3.Connection,
    records: list[dict],
) -> ImportMergeResult:
    imported = 0
    skipped = 0
    conflicts = 0

    for item in records:
        title = str(item.get("title", "")).strip()
        content = str(item.get("content") or item.get("body") or "").strip()
        if not title:
            skipped += 1
            continue

        confidence = float(item.get("confidence", 1.0))
        existing = conn.execute(
            """
            SELECT id, confidence FROM nodes
            WHERE title = ? AND valid_until IS NULL
            LIMIT 1
            """,
            (title,),
        ).fetchone()

        try:
            if existing is None:
                _remember_import_neuron(
                    conn,
                    title=title,
                    content=content,
                    item=item,
                    confidence=confidence,
                    node_id=item.get("id"),
                )
                imported += 1
                continue

            existing_conf = float(existing["confidence"] or 1.0)
            if confidence > existing_conf:
                replacement = _remember_import_neuron(
                    conn,
                    title=title,
                    content=content,
                    item=item,
                    confidence=confidence,
                )
                supersede_neuron(conn, existing["id"], replacement=replacement)
                imported += 1
            elif confidence == existing_conf:
                duplicate = _remember_import_neuron(
                    conn,
                    title=title,
                    content=content,
                    item=item,
                    confidence=confidence,
                )
                edge_id = new_ulid()
                from brainkm.services.audit import utc_now_iso

                now = utc_now_iso()
                conn.execute(
                    """
                    INSERT INTO edges (id, from_id, to_id, relationship, weight, created_at, updated_at)
                    VALUES (?, ?, ?, 'conflicts_with', 0.5, ?, ?)
                    """,
                    (edge_id, duplicate.id, existing["id"], now, now),
                )
                conflicts += 1
                imported += 1
            else:
                skipped += 1
        except RedactionBlockedError as exc:
            logger.warning("Skipped import neuron blocked by redaction: %s", exc)
            skipped += 1

    return ImportMergeResult(imported=imported, skipped=skipped, conflicts=conflicts)


def import_json_merge(
    path: Path,
    *,
    project_dir: Path | None = None,
) -> ImportMergeResult:
    migrate(project_dir=project_dir, run_integrity_check=False)
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload if isinstance(payload, list) else payload.get("neurons", [])
    parsed = _parse_export_records(records if isinstance(records, list) else [])

    conn = connect(brain_db_path(project_dir))
    try:
        result = import_neurons_merge(conn, parsed)
        conn.commit()
    finally:
        conn.close()
    return result
