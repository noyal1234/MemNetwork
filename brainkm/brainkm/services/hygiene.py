"""One-time / on-demand hygiene — soft-archive noisy memory neurons."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from brainkm.services.memory import forget_neuron
from brainkm.services.quality import passes_stored_neuron_gate


@dataclass(frozen=True)
class HygieneResult:
    scanned: int
    archived: int
    kept: int
    archived_ids: tuple[str, ...]


def archive_expired_commits(
    conn: sqlite3.Connection,
    *,
    retention_days: int = 90,
    dry_run: bool = False,
    limit: int | None = None,
) -> list[str]:
    """Soft-archive old commit nodes with no relates_to edges to active memories."""
    from brainkm.services.git_note import COMMIT_KIND

    cutoff = (datetime.now(UTC) - timedelta(days=max(7, retention_days))).isoformat()
    sql = """
        SELECT c.id
        FROM nodes c
        WHERE c.kind = ?
          AND c.valid_until IS NULL
          AND c.created_at < ?
          AND NOT EXISTS (
            SELECT 1 FROM edges e
            JOIN nodes m ON m.id = e.to_id
            WHERE e.from_id = c.id
              AND e.relationship = 'relates_to'
              AND m.valid_until IS NULL
              AND m.kind IN ('memory', 'procedure', 'concept')
          )
        ORDER BY c.created_at ASC
    """
    params: list[object] = [COMMIT_KIND, cutoff]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))
    rows = conn.execute(sql, params).fetchall()
    archived: list[str] = []
    for (node_id,) in rows:
        archived.append(node_id)
        if not dry_run:
            forget_neuron(
                conn,
                node_id,
                reason=f"hygiene: commit older than {retention_days}d without active links",
            )
    return archived


def purge_noisy_neurons(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
    limit: int | None = None,
    decay: bool = False,
    unused_days: int = 90,
    config: object | None = None,
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
    # Observation TTL sweep
    if config is not None:
        from brainkm.models.brain_config import BrainConfig
        from brainkm.services.lifecycle import archive_expired_observations

        if isinstance(config, BrainConfig):
            ttl_ids = archive_expired_observations(conn, config=config, dry_run=dry_run)
            for node_id in ttl_ids:
                if node_id not in archived_ids:
                    archived_ids.append(node_id)
            commit_ids = archive_expired_commits(
                conn,
                retention_days=config.git.commit_retention_days,
                dry_run=dry_run,
                limit=limit,
            )
            for node_id in commit_ids:
                if node_id not in archived_ids:
                    archived_ids.append(node_id)
    else:
        # auto_hygiene path without config: still sweep commits at default retention
        commit_ids = archive_expired_commits(
            conn,
            retention_days=90,
            dry_run=dry_run,
            limit=limit,
        )
        for node_id in commit_ids:
            if node_id not in archived_ids:
                archived_ids.append(node_id)
    if decay:
        from brainkm.models.brain_config import BrainConfig
        from brainkm.services.consolidate import decay_unused_neurons
        from brainkm.services.learning import (
            decay_co_activation_edges,
            purge_session_learning_state,
        )

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
        learning = (
            config.learning
            if isinstance(config, BrainConfig)
            else BrainConfig().learning
        )
        decay_co_activation_edges(
            conn,
            idle_days=learning.co_activation_idle_days,
            decay_factor=learning.co_activation_decay_factor,
            min_weight=learning.co_activation_min_weight,
            dry_run=dry_run,
        )
        if not dry_run:
            purge_session_learning_state(
                conn,
                retention_days=learning.session_state_retention_days,
            )
    if not dry_run and archived_ids:
        conn.commit()
    # Collapse historical duplicate tool_chain titles (Write→Shell spam).
    from brainkm.services.procedures import (
        archive_ignored_procedures,
        dedupe_tool_chain_procedures,
    )

    proc_archived = dedupe_tool_chain_procedures(conn, dry_run=dry_run)
    for node_id in proc_archived:
        if node_id not in archived_ids:
            archived_ids.append(node_id)
            kept = max(0, kept - 1)
    from brainkm.models.brain_config import BrainConfig

    learning = (
        config.learning if isinstance(config, BrainConfig) else BrainConfig().learning
    )
    ignored_procs = archive_ignored_procedures(
        conn,
        max_ignore_rate=learning.promote_max_ignore_rate,
        min_injected_count=learning.archive_min_injected_count,
        half_life_days=learning.promote_ignore_half_life_days,
        dry_run=dry_run,
    )
    for node_id in ignored_procs:
        if node_id not in archived_ids:
            archived_ids.append(node_id)
            kept = max(0, kept - 1)
    if not dry_run and (proc_archived or ignored_procs):
        conn.commit()
    return HygieneResult(
        scanned=len(rows) + len(proc_archived) + len(ignored_procs),
        archived=len(archived_ids),
        kept=kept,
        archived_ids=tuple(archived_ids),
    )
