"""Post-write indexing: about_file/symbol edges + deterministic concepts."""

from __future__ import annotations

import json
import sqlite3

from brainkm.services.concepts import materialize_concepts_for_neuron
from brainkm.services.remember_links import link_neuron_to_code


def index_neuron_links(
    conn: sqlite3.Connection,
    neuron_id: str,
    *,
    title: str,
    content: str | None,
    tags: list[str] | None = None,
    kind: str = "memory",
) -> list[str]:
    """Link code neighbors and materialize concepts. Returns linked code ids."""
    body = content or ""
    linked = link_neuron_to_code(conn, neuron_id, title=title, content=body)
    tag_list = tags
    if tag_list is None:
        row = conn.execute("SELECT tags FROM nodes WHERE id = ?", (neuron_id,)).fetchone()
        if row and row[0]:
            try:
                raw = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                tag_list = list(raw) if isinstance(raw, list) else []
            except json.JSONDecodeError:
                tag_list = []
    materialize_concepts_for_neuron(
        conn,
        neuron_id,
        title=title,
        content=body,
        tags=tag_list or [],
        kind=kind,
    )
    return linked
