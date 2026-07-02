"""V2 procedure promotion from co-activation signals."""

from __future__ import annotations

import hashlib
import sqlite3

from brainkm.models.brain_config import BrainConfig
from brainkm.services.memory import create_neuron, new_ulid
from brainkm.services.search import resolve_node_ref

_INTERNAL_TOOLS = frozenset({"remember", "recall", "context_pack", "session_status", "traverse", "forget"})


def find_promotable_pairs(conn: sqlite3.Connection, *, threshold: int) -> list[tuple[str, str]]:
    rows = conn.execute(
        """
        SELECT from_id, to_id
        FROM edges
        WHERE relationship = 'co_activated'
          AND weight >= ?
          AND from_id < to_id
        ORDER BY weight DESC, updated_at DESC
        """,
        (threshold,),
    ).fetchall()
    return [(row["from_id"], row["to_id"]) for row in rows]


def _procedure_key(neuron_ids: list[str]) -> str:
    raw = "|".join(sorted(neuron_ids))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _existing_procedure(conn: sqlite3.Connection, key: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM nodes
        WHERE valid_until IS NULL AND kind = 'procedure' AND source = ?
        LIMIT 1
        """,
        (f"learning:proc:{key}",),
    ).fetchone()
    return row is not None


def _node_titles(conn: sqlite3.Connection, neuron_ids: list[str]) -> list[str]:
    titles: list[str] = []
    for node_id in neuron_ids:
        row = conn.execute(
            "SELECT title FROM nodes WHERE id = ? AND valid_until IS NULL",
            (node_id,),
        ).fetchone()
        if row is not None:
            titles.append(row["title"])
    return titles


def upsert_procedure_neuron(
    conn: sqlite3.Connection,
    *,
    neuron_ids: list[str],
    tool_names: list[str],
    session_id: str | None,
) -> str | None:
    if len(neuron_ids) < 2:
        return None
    key = _procedure_key(neuron_ids)
    if _existing_procedure(conn, key):
        return None

    external_tools = [name for name in tool_names if name not in _INTERNAL_TOOLS]
    if len(set(external_tools)) < 2:
        return None

    titles = _node_titles(conn, neuron_ids)
    top_title = titles[0] if titles else "learned context"
    title = f"{' + '.join(list(dict.fromkeys(external_tools))[:2])}: {top_title}"[:160]
    steps = [f"{index + 1}. {line}" for index, line in enumerate(titles[:5])]
    body = "\n".join(steps) if steps else "1. Reuse previously successful tool chain."
    record = create_neuron(
        conn,
        title=title,
        content=body,
        kind="procedure",
        subtype="tool_chain",
        session_id=session_id,
        source=f"learning:proc:{key}",
        node_id=new_ulid(),
    )
    from_id = record.id
    for target in neuron_ids:
        conn.execute(
            """
            INSERT OR IGNORE INTO edges (id, from_id, to_id, relationship, weight, created_at, updated_at)
            VALUES (?, ?, ?, 'spawned', 1.0, datetime('now'), datetime('now'))
            """,
            (new_ulid(), from_id, target),
        )
    return record.id


def check_and_promote(
    conn: sqlite3.Connection,
    session_id: str | None,
    *,
    config: BrainConfig,
) -> list[str]:
    from brainkm.services.learning import get_learning_window

    window = get_learning_window()
    promoted: list[str] = []
    for first, second in find_promotable_pairs(conn, threshold=config.learning.co_activation_threshold):
        # Skip invalid/archived references quickly.
        if resolve_node_ref(conn, first) is None or resolve_node_ref(conn, second) is None:
            continue
        created = upsert_procedure_neuron(
            conn,
            neuron_ids=[first, second],
            tool_names=window.recent_tool_names(session_id),
            session_id=session_id,
        )
        if created is not None:
            promoted.append(created)
    return promoted

