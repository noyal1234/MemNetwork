"""One-time / on-demand hygiene — soft-archive noisy memory neurons."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from brainkm.services.memory import forget_neuron
from brainkm.services.quality import passes_stored_neuron_gate


@dataclass(frozen=True)
class HygieneResult:
    scanned: int
    archived: int
    kept: int
    archived_ids: tuple[str, ...]


def purge_noisy_neurons(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
    limit: int | None = None,
    decay: bool = False,
    unused_days: int = 90,
) -> HygieneResult:
    """Re-run the quality gate over active memory neurons and soft-archive failures."""
    sql = """
        SELECT id, title, content
        FROM nodes
        WHERE valid_until IS NULL AND kind = 'memory'
        ORDER BY created_at ASC
    """
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql).fetchall()
    archived_ids: list[str] = []
    kept = 0
    for row in rows:
        if passes_stored_neuron_gate(title=row["title"] or "", content=row["content"]):
            kept += 1
            continue
        archived_ids.append(row["id"])
        if not dry_run:
            forget_neuron(
                conn,
                row["id"],
                reason="hygiene: failed quality gate (noise/chrome/boilerplate)",
            )
    if decay:
        from brainkm.services.consolidate import decay_unused_neurons

        decay_result = decay_unused_neurons(
            conn,
            unused_days=unused_days,
            dry_run=dry_run,
            limit=limit,
        )
        for node_id in decay_result.archived_ids:
            if node_id not in archived_ids:
                archived_ids.append(node_id)
                kept = max(0, kept - 1)
    if not dry_run and archived_ids:
        conn.commit()
    return HygieneResult(
        scanned=len(rows),
        archived=len(archived_ids),
        kept=kept,
        archived_ids=tuple(archived_ids),
    )
