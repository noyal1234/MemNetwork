"""Cross-turn session neuron-id suppression (context-rot control)."""

from __future__ import annotations

import sqlite3

from brainkm.services.budget import BudgetLine
from brainkm.services.session_activity import load_session_neuron_ids


def filter_already_injected(
    lines: list[BudgetLine],
    *,
    conn: sqlite3.Connection,
    session_id: str | None,
    allow_priority_at_most: int = 1,
    force_ids: set[str] | None = None,
) -> tuple[list[BudgetLine], list[str]]:
    """Drop lines whose neuron_id was already injected this session.

    Keep decision/rule priority <= allow_priority_at_most and force_ids.
    Returns (kept, suppressed_ids).
    """
    if not session_id or not lines:
        return lines, []
    seen = load_session_neuron_ids(conn, session_id)
    if not seen:
        return lines, []
    force = force_ids or set()
    kept: list[BudgetLine] = []
    suppressed: list[str] = []
    for line in lines:
        if line.node_id in force:
            kept.append(line)
            continue
        if line.node_id in seen and line.priority > allow_priority_at_most:
            suppressed.append(line.node_id)
            continue
        kept.append(line)
    return kept, suppressed


def reinject_rate(new_ids: list[str], already: set[str]) -> float:
    if not new_ids:
        return 0.0
    hits = sum(1 for nid in new_ids if nid in already)
    return hits / len(new_ids)
