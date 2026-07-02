"""V2: Project-scoped tool node registry (cap 20)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from brainkm.services.memory import create_neuron, new_ulid


@dataclass(frozen=True)
class ToolNode:
    node_id: str
    name: str
    description: str | None


def list_tool_nodes(conn: sqlite3.Connection, *, limit: int = 20) -> list[ToolNode]:
    rows = conn.execute(
        """
        SELECT id, title, content
        FROM nodes
        WHERE valid_until IS NULL AND kind = 'tool'
        ORDER BY use_count DESC, updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        ToolNode(node_id=row["id"], name=row["title"], description=row["content"])
        for row in rows
    ]


def register_tool_node(
    conn: sqlite3.Connection,
    *,
    name: str,
    description: str | None = None,
    max_tools: int = 20,
) -> ToolNode:
    existing = list_tool_nodes(conn, limit=max_tools + 1)
    if len(existing) >= max_tools:
        msg = f"tool node cap reached ({max_tools})"
        raise ValueError(msg)

    record = create_neuron(
        conn,
        title=name,
        content=description,
        kind="tool",
        subtype=None,
        node_id=new_ulid(),
    )
    return ToolNode(node_id=record.id, name=record.title, description=record.content)


def register_tool_node_idempotent(
    conn: sqlite3.Connection,
    *,
    name: str,
    description: str | None = None,
    max_tools: int = 20,
) -> ToolNode:
    row = conn.execute(
        """
        SELECT id, title, content
        FROM nodes
        WHERE valid_until IS NULL AND kind = 'tool' AND title = ?
        LIMIT 1
        """,
        (name,),
    ).fetchone()
    if row is not None:
        return ToolNode(node_id=row["id"], name=row["title"], description=row["content"])
    return register_tool_node(conn, name=name, description=description, max_tools=max_tools)
