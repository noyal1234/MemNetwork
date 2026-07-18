"""V2 procedure promotion from co-activation signals."""

from __future__ import annotations

import hashlib
import sqlite3

from brainkm.models.brain_config import BrainConfig
from brainkm.services.memory import new_ulid, remember_neuron
from brainkm.services.search import resolve_node_ref

_INTERNAL_TOOLS = frozenset(
    {
        "remember",
        "recall",
        "context_pack",
        "session_status",
        "traverse",
        "forget",
        "brain_stats",
        "graph_sync",
        "__recall__",
    }
)


def ordered_external_tools(tool_names: list[str]) -> list[str]:
    """First-seen order of external (non-brainkm) tools in the session window."""
    seen: set[str] = set()
    ordered: list[str] = []
    for name in tool_names:
        if not name or name in _INTERNAL_TOOLS or name in seen:
            continue
        seen.add(name)
        ordered.append(name)
    return ordered


def find_promotable_pairs(
    conn: sqlite3.Connection,
    *,
    threshold: int,
    session_neuron_ids: set[str] | None = None,
) -> list[tuple[str, str]]:
    """Return co_activated pairs at/above threshold.

    When ``session_neuron_ids`` is provided, only pairs where both endpoints are
    in that set are returned (empty set → nothing). Omit the filter only for
    diagnostics; ``check_and_promote`` always scopes to the current session.
    """
    if session_neuron_ids is not None and len(session_neuron_ids) < 2:
        return []

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
    pairs = [(row["from_id"], row["to_id"]) for row in rows]
    if session_neuron_ids is None:
        return pairs
    return [
        (first, second)
        for first, second in pairs
        if first in session_neuron_ids and second in session_neuron_ids
    ]


def _procedure_key(tool_names: list[str], neuron_ids: list[str]) -> str:
    tools = "|".join(ordered_external_tools(tool_names))
    neurons = "|".join(sorted(neuron_ids))
    raw = f"{tools}::{neurons}"
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


def _format_procedure_body(tools: list[str], context_titles: list[str]) -> str:
    steps = [f"{index + 1}. {name}" for index, name in enumerate(tools)]
    lines = [
        f"Tools: {' → '.join(tools)}",
        "",
        *steps,
    ]
    if context_titles:
        lines.extend(["", "Related context:"])
        lines.extend(f"- {title}" for title in context_titles[:5])
    return "\n".join(lines)


def upsert_procedure_neuron(
    conn: sqlite3.Connection,
    *,
    neuron_ids: list[str],
    tool_names: list[str],
    session_id: str | None,
) -> str | None:
    if len(neuron_ids) < 2:
        return None

    tools = ordered_external_tools(tool_names)
    if len(tools) < 2:
        return None

    key = _procedure_key(tool_names, neuron_ids)
    if _existing_procedure(conn, key):
        return None

    titles = _node_titles(conn, neuron_ids)
    chain = " → ".join(tools[:4])
    title = chain[:160]
    body = _format_procedure_body(tools, titles)
    record = remember_neuron(
        conn,
        title=title,
        content=body,
        kind="procedure",
        subtype="tool_chain",
        session_id=session_id,
        source=f"learning:proc:{key}",
        node_id=new_ulid(),
        tags=["procedure", "tool_chain", *tools[:3]],
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
        # Prefer high use_count sources; still link all for lineage.
        conn.execute(
            """
            INSERT OR IGNORE INTO edges (id, from_id, to_id, relationship, weight, created_at, updated_at)
            VALUES (?, ?, ?, 'distilled_from', 0.9, datetime('now'), datetime('now'))
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
    from brainkm.services.learning import load_recent_neuron_ids, load_recent_tool_names

    if not session_id:
        return []

    tool_names = load_recent_tool_names(
        conn,
        session_id,
        limit=config.learning.session_window_size,
    )
    session_neuron_ids = set(
        load_recent_neuron_ids(
            conn,
            session_id,
            limit=config.learning.session_window_size,
        )
    )
    if len(session_neuron_ids) < 2 or len(ordered_external_tools(tool_names)) < 2:
        return []

    promoted: list[str] = []
    for first, second in find_promotable_pairs(
        conn,
        threshold=config.learning.co_activation_threshold,
        session_neuron_ids=session_neuron_ids,
    ):
        # Skip invalid/archived references quickly.
        if resolve_node_ref(conn, first) is None or resolve_node_ref(conn, second) is None:
            continue
        created = upsert_procedure_neuron(
            conn,
            neuron_ids=[first, second],
            tool_names=tool_names,
            session_id=session_id,
        )
        if created is not None:
            promoted.append(created)
    return promoted
