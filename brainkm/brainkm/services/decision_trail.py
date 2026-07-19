"""Follow supersedes edges for temporal decision history."""

from __future__ import annotations

import sqlite3

from brainkm.models.schemas import DecisionTrailEntry


def build_decision_trail(
    conn: sqlite3.Connection,
    seed_ids: list[str],
    *,
    max_entries: int = 12,
    max_depth: int = 6,
) -> list[DecisionTrailEntry]:
    """Return newest-first supersede chains rooted at seed decision neurons.

    Edge convention: ``new --supersedes--> old``. Walking outbound from a live
    decision yields the history it replaced.
    """
    trail: list[DecisionTrailEntry] = []
    seen: set[str] = set()

    for seed_id in seed_ids:
        if len(trail) >= max_entries:
            break
        row = conn.execute(
            """
            SELECT id, title, subtype, valid_from, valid_until
            FROM nodes WHERE id = ?
            """,
            (seed_id,),
        ).fetchone()
        if row is None:
            continue
        if row["id"] not in seen:
            seen.add(row["id"])
            trail.append(
                DecisionTrailEntry(
                    node_id=row["id"],
                    title=row["title"],
                    subtype=row["subtype"],
                    valid_from=row["valid_from"],
                    valid_until=row["valid_until"],
                    superseded_by=None,
                )
            )

        current = seed_id
        depth = 0
        while depth < max_depth and len(trail) < max_entries:
            edge = conn.execute(
                """
                SELECT to_id FROM edges
                WHERE from_id = ? AND relationship = 'supersedes'
                LIMIT 1
                """,
                (current,),
            ).fetchone()
            if edge is None:
                break
            old_id = edge[0]
            if old_id in seen:
                break
            old = conn.execute(
                """
                SELECT id, title, subtype, valid_from, valid_until
                FROM nodes WHERE id = ?
                """,
                (old_id,),
            ).fetchone()
            if old is None:
                break
            seen.add(old_id)
            trail.append(
                DecisionTrailEntry(
                    node_id=old["id"],
                    title=old["title"],
                    subtype=old["subtype"],
                    valid_from=old["valid_from"],
                    valid_until=old["valid_until"],
                    superseded_by=current,
                )
            )
            current = old_id
            depth += 1

    return trail


def should_include_history(
    *,
    include_history: bool | None,
    intent: str | None,
    query: str,
) -> bool:
    """Auto-enable history for decision/why/history intents unless explicitly off."""
    if include_history is not None:
        return include_history
    intent_l = (intent or "").lower()
    if intent_l in {"decision", "why", "history", "rule"}:
        return True
    q = query.lower()
    return any(
        token in q
        for token in ("why ", "why did", "history", "instead of", "rather than", "supersede")
    )


def format_decision_history_section(entries: list[DecisionTrailEntry]) -> list[str]:
    """Compact pack_text lines for a Decision history section."""
    if not entries:
        return []
    lines = ["## Decision history", ""]
    for entry in entries[:8]:
        status = "current" if entry.valid_until is None else f"until {entry.valid_until[:10]}"
        lines.append(f"- [{status}] {entry.title}")
    lines.append("")
    return lines
