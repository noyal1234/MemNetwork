"""Provenance chains: distilled_from edges, chunk_sources, supersedes."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from brainkm.services.memory import token_count


@dataclass(frozen=True)
class ProvenanceLink:
    via: str
    id: str
    session_id: str | None = None
    title: str | None = None


@dataclass(frozen=True)
class ProvenanceChain:
    node_id: str
    session_id: str | None
    links: list[ProvenanceLink]


def load_provenance(conn: sqlite3.Connection, node_id: str) -> ProvenanceChain:
    row = conn.execute(
        "SELECT session_id FROM nodes WHERE id = ?",
        (node_id,),
    ).fetchone()
    session_id = row[0] if row else None
    links: list[ProvenanceLink] = []

    for edge in conn.execute(
        """
        SELECT e.to_id, e.relationship, n.title, n.session_id, n.subtype
        FROM edges e
        JOIN nodes n ON n.id = e.to_id
        WHERE e.from_id = ?
          AND e.relationship IN ('distilled_from', 'spawned', 'supersedes')
        ORDER BY e.created_at ASC
        """,
        (node_id,),
    ).fetchall():
        links.append(
            ProvenanceLink(
                via=edge[1],
                id=edge[0],
                session_id=edge[3],
                title=edge[2],
            )
        )

    for chunk in conn.execute(
        """
        SELECT cs.chunk_id, sc.session_id
        FROM chunk_sources cs
        LEFT JOIN session_chunks sc ON sc.id = cs.chunk_id
        WHERE cs.neuron_id = ?
        ORDER BY cs.distill_ts ASC
        LIMIT 20
        """,
        (node_id,),
    ).fetchall():
        links.append(
            ProvenanceLink(
                via="chunk",
                id=chunk[0],
                session_id=chunk[1],
            )
        )

    return ProvenanceChain(node_id=node_id, session_id=session_id, links=links)


def compact_sources_for_node(
    conn: sqlite3.Connection,
    node_id: str,
    *,
    max_links: int = 3,
) -> list[dict[str, str | None]]:
    """Token-aware compact sources payload for MCP responses."""
    chain = load_provenance(conn, node_id)
    out: list[dict[str, str | None]] = []
    for link in chain.links[:max_links]:
        out.append(
            {
                "session_id": link.session_id or chain.session_id,
                "id": link.id,
                "via": link.via,
            }
        )
    return out


def format_provenance_report(conn: sqlite3.Connection, node_id: str) -> str:
    chain = load_provenance(conn, node_id)
    lines = [
        f"node={chain.node_id}",
        f"session_id={chain.session_id or '-'}",
        f"links={len(chain.links)}",
    ]
    for link in chain.links:
        title = f" title={link.title!r}" if link.title else ""
        lines.append(f"  - via={link.via} id={link.id} session={link.session_id or '-'}{title}")
    # Keep report bounded for CLI.
    text = "\n".join(lines)
    if token_count(text) > 800:
        return "\n".join(lines[:40]) + "\n…"
    return text


def sources_json_budget(sources: list[dict[str, str | None]], *, max_tokens: int = 80) -> str:
    payload = json.dumps(sources, separators=(",", ":"))
    if token_count(payload) <= max_tokens:
        return payload
    return json.dumps(sources[:1], separators=(",", ":"))
