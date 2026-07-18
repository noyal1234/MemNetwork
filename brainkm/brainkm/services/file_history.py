"""File-centric memory neighborhood: about_file / about_symbol inbound links."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class FileHistoryItem:
    node_id: str
    kind: str
    subtype: str | None
    title: str
    relationship: str
    use_count: int
    session_id: str | None
    content: str | None = None


def resolve_code_node_for_path(conn: sqlite3.Connection, path: str) -> str | None:
    row = conn.execute(
        """
        SELECT id FROM nodes
        WHERE kind = 'code' AND path = ? AND valid_until IS NULL
        LIMIT 1
        """,
        (path,),
    ).fetchone()
    if row:
        return row[0]
    base = path.rsplit("/", 1)[-1]
    row = conn.execute(
        """
        SELECT id FROM nodes
        WHERE kind = 'code' AND path LIKE ? AND valid_until IS NULL
        ORDER BY LENGTH(path) ASC
        LIMIT 1
        """,
        (f"%/{base}",),
    ).fetchone()
    return row[0] if row else None


def file_history(
    conn: sqlite3.Connection,
    path: str,
    *,
    limit: int = 20,
) -> tuple[str | None, list[FileHistoryItem]]:
    """Return (code_node_id, linked memories/episodes/procedures)."""
    code_id = resolve_code_node_for_path(conn, path)
    if code_id is None:
        return None, []
    rows = conn.execute(
        """
        SELECT n.id, n.kind, n.subtype, n.title, e.relationship,
               COALESCE(n.use_count, 0), n.session_id, n.content
        FROM edges e
        JOIN nodes n ON n.id = e.from_id
        WHERE e.to_id = ?
          AND e.relationship IN ('about_file', 'about_symbol', 'relates_to')
          AND n.valid_until IS NULL
          AND n.kind IN ('memory', 'procedure', 'concept')
        ORDER BY COALESCE(n.use_count, 0) DESC, n.updated_at DESC
        LIMIT ?
        """,
        (code_id, limit),
    ).fetchall()
    items = [
        FileHistoryItem(
            node_id=row[0],
            kind=row[1],
            subtype=row[2],
            title=row[3],
            relationship=row[4],
            use_count=int(row[5] or 0),
            session_id=row[6],
            content=row[7],
        )
        for row in rows
    ]
    return code_id, items


def seed_ids_for_path(conn: sqlite3.Connection, path: str, *, limit: int = 8) -> list[str]:
    code_id, items = file_history(conn, path, limit=limit)
    seeds: list[str] = []
    if code_id:
        seeds.append(code_id)
    seeds.extend(item.node_id for item in items)
    return seeds
