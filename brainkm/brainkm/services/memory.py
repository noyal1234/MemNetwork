"""Neuron lifecycle — temporal-lite via audit_log; valid_until is trigger-derived."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import ulid

from brainkm.adapters.redaction import require_clean
from brainkm.services.audit import append_event, utc_now_iso


@lru_cache(maxsize=1)
def _tiktoken_encoding():
    import tiktoken

    return tiktoken.get_encoding("cl100k_base")


def token_count(text: str) -> int:
    if not text:
        return 0
    try:
        return len(_tiktoken_encoding().encode(text))
    except Exception:
        return max(1, len(text) // 4)


@dataclass(frozen=True)
class NeuronRecord:
    id: str
    kind: str
    subtype: str | None
    title: str
    content: str | None
    valid_from: str
    valid_until: str | None
    session_id: str | None


@dataclass(frozen=True)
class NeuronContext:
    subtype: str | None
    title: str
    tags: list[str]


def new_ulid() -> str:
    return str(ulid.new())


def _row_to_record(row: sqlite3.Row) -> NeuronRecord:
    return NeuronRecord(
        id=row["id"],
        kind=row["kind"],
        subtype=row["subtype"],
        title=row["title"],
        content=row["content"],
        valid_from=row["valid_from"],
        valid_until=row["valid_until"],
        session_id=row["session_id"],
    )


def get_node(conn: sqlite3.Connection, node_id: str) -> NeuronRecord | None:
    row = conn.execute(
        """
        SELECT id, kind, subtype, title, content, valid_from, valid_until, session_id
        FROM nodes
        WHERE id = ?
        """,
        (node_id,),
    ).fetchone()
    return _row_to_record(row) if row else None


def create_neuron(
    conn: sqlite3.Connection,
    *,
    title: str,
    content: str | None = None,
    kind: str = "memory",
    subtype: str | None = "fact",
    path: str | None = None,
    tags: list[str] | None = None,
    source: str | None = None,
    session_id: str | None = None,
    confidence: float = 1.0,
    valid_from: str | None = None,
    node_id: str | None = None,
) -> NeuronRecord:
    """Insert a neuron and append a `created` audit event.

    Never sets valid_until — that column is maintained only by audit_log triggers.
    """
    now = utc_now_iso()
    neuron_id = node_id or new_ulid()
    effective_valid_from = valid_from or now
    tags_json = json.dumps(tags or [], separators=(",", ":"))
    body = content or ""
    tokens = token_count(f"{title}\n{body}")

    conn.execute(
        """
        INSERT INTO nodes (
          id, kind, subtype, title, content, path, tags, source,
          confidence, token_count, valid_from, ingested_at, session_id,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            neuron_id,
            kind,
            subtype,
            title,
            body,
            path,
            tags_json,
            source,
            confidence,
            tokens,
            effective_valid_from,
            now,
            session_id,
            now,
            now,
        ),
    )

    append_event(
        conn,
        "created",
        node_id=neuron_id,
        payload={
            "valid_from": effective_valid_from,
            "session_id": session_id,
            "kind": kind,
            "subtype": subtype,
        },
        ts=now,
    )

    record = get_node(conn, neuron_id)
    assert record is not None
    return record


def remember_neuron(
    conn: sqlite3.Connection,
    *,
    title: str,
    content: str | None = None,
    source: str | None = None,
    kind: str = "memory",
    subtype: str | None = "fact",
    path: str | None = None,
    tags: list[str] | None = None,
    session_id: str | None = None,
    confidence: float = 1.0,
    valid_from: str | None = None,
    node_id: str | None = None,
    compress: bool = False,
    max_body_tokens: int = 120,
    semantic_enabled: bool = False,
) -> NeuronRecord:
    """Persist a neuron after secret redaction and injection scanning.

    Writes to live brain.db only — does not mutate the frozen SessionStart snapshot.
    Mid-session remembers are visible to ``recall_live`` in the same session.
    """
    cleaned = require_clean(title, content or "", source=source)
    body = cleaned.content
    # Tags enter nodes_fts — redact each one through the same chokepoint as title/body.
    # Hard-block secrets/injection raise RedactionBlockedError (same as title/content).
    cleaned_tags: list[str] | None = None
    if tags:
        cleaned_tags = []
        for tag in tags:
            tag_text = str(tag).strip() if tag is not None else ""
            if not tag_text:
                continue
            cleaned_tag = require_clean("", tag_text, source=source)
            if cleaned_tag.content.strip():
                cleaned_tags.append(cleaned_tag.content.strip())
    if compress and body:
        from brainkm.services.compress import compress_body

        # Skip lossy pipeline for durable decision/rule store (extractive cap only).
        use_pipeline = subtype not in {"decision", "rule"}
        body = compress_body(
            body,
            max_tokens=max_body_tokens,
            kind=kind,
            subtype=subtype,
            use_pipeline=use_pipeline,
        )
    record = create_neuron(
        conn,
        title=cleaned.title,
        content=body,
        kind=kind,
        subtype=subtype,
        path=path,
        tags=cleaned_tags,
        source=source,
        session_id=session_id,
        confidence=confidence,
        valid_from=valid_from,
        node_id=node_id,
    )
    if semantic_enabled and kind == "memory":
        from brainkm.services.semantic import embed_neuron_if_enabled

        embed_neuron_if_enabled(
            conn,
            record.id,
            title=record.title,
            content=record.content,
            semantic_enabled=True,
        )
    return record


def supersede_neuron(
    conn: sqlite3.Connection,
    old_node_id: str,
    *,
    replacement: NeuronRecord | None = None,
    replacement_id: str | None = None,
    title: str | None = None,
    content: str | None = None,
    kind: str = "memory",
    subtype: str | None = "fact",
    session_id: str | None = None,
    effective_at: str | None = None,
    reasoning: str | None = None,
    rejected_alternatives: list[str] | None = None,
    valid_from_meta: str | None = None,
) -> tuple[NeuronRecord, NeuronRecord]:
    """Retire old neuron via audit_log `superseded`; valid_until set by trigger only."""
    old = get_node(conn, old_node_id)
    if old is None:
        msg = f"node not found: {old_node_id}"
        raise ValueError(msg)
    if old.valid_until is not None:
        msg = f"node already inactive: {old_node_id}"
        raise ValueError(msg)

    if replacement is not None:
        new_record = replacement
        new_id = replacement.id
    elif replacement_id is not None:
        existing = get_node(conn, replacement_id)
        if existing is None:
            msg = f"replacement node not found: {replacement_id}"
            raise ValueError(msg)
        new_record = existing
        new_id = replacement_id
    else:
        if title is None:
            msg = "title required when creating replacement neuron"
            raise ValueError(msg)
        new_record = remember_neuron(
            conn,
            title=title,
            content=content,
            kind=kind,
            subtype=subtype,
            session_id=session_id,
            valid_from=effective_at,
            source="mcp_supersede",
        )
        new_id = new_record.id

    now = effective_at or utc_now_iso()
    edge_id = new_ulid()
    meta: dict[str, Any] = {}
    if valid_from_meta:
        meta["valid_from"] = valid_from_meta
    if reasoning:
        meta["reasoning"] = reasoning
    if rejected_alternatives:
        meta["rejected_alternatives"] = rejected_alternatives[:8]
    meta_json = json.dumps(meta, separators=(",", ":")) if meta else None
    # meta_json column added in migration 007 — tolerate older DBs.
    try:
        conn.execute(
            """
            INSERT INTO edges (id, from_id, to_id, relationship, weight, created_at, updated_at,
                meta_json)
            VALUES (?, ?, ?, 'supersedes', 1.0, ?, ?, ?)
            """,
            (edge_id, new_id, old_node_id, now, now, meta_json),
        )
    except sqlite3.OperationalError:
        conn.execute(
            """
            INSERT INTO edges (id, from_id, to_id, relationship, weight, created_at, updated_at)
            VALUES (?, ?, ?, 'supersedes', 1.0, ?, ?)
            """,
            (edge_id, new_id, old_node_id, now, now),
        )

    payload: dict[str, Any] = {"valid_until": now, "superseded_by": new_id}
    if meta:
        payload.update(meta)
    append_event(
        conn,
        "superseded",
        node_id=old_node_id,
        payload=payload,
        ts=now,
    )

    retired = get_node(conn, old_node_id)
    assert retired is not None
    if retired.valid_until is None:
        msg = "valid_until was not materialized from audit_log supersede event"
        raise RuntimeError(msg)

    return new_record, retired


def forget_neuron(
    conn: sqlite3.Connection,
    node_id: str,
    *,
    reason: str | None = None,
    effective_at: str | None = None,
) -> NeuronRecord:
    """Soft-archive a neuron via audit_log `forgotten`; valid_until set by trigger only."""
    existing = get_node(conn, node_id)
    if existing is None:
        msg = f"node not found: {node_id}"
        raise ValueError(msg)
    if existing.valid_until is not None:
        return existing

    now = effective_at or utc_now_iso()
    payload: dict[str, Any] = {"valid_until": now}
    if reason:
        payload["reason"] = reason

    append_event(conn, "forgotten", node_id=node_id, payload=payload, ts=now)

    archived = get_node(conn, node_id)
    assert archived is not None
    if archived.valid_until is None:
        msg = "valid_until was not materialized from audit_log forgotten event"
        raise RuntimeError(msg)
    return archived


def flush_use_counts(conn: sqlite3.Connection, session_id: str | None) -> int:
    """Increment use_count for neurons recalled/injected this session (SessionEnd flush)."""
    from brainkm.services.session_activity import flush_use_counts as _flush

    return _flush(conn, session_id)


def is_active_at(record: NeuronRecord, at: str) -> bool:
    if record.valid_from > at:
        return False
    if record.valid_until is not None and record.valid_until <= at:
        return False
    return True


def recent_neuron_context(
    conn: sqlite3.Connection,
    *,
    limit: int = 5,
) -> list[NeuronContext]:
    """Most recent non-ephemeral memory neurons, for prompt grounding.

    Excludes ``subtype='context'`` (session-status neurons from
    ``services/session_status.py``) since those are ephemeral working-state,
    not durable facts, and would add noise rather than grounding.
    """
    rows = conn.execute(
        """
        SELECT title, subtype, tags
        FROM nodes
        WHERE kind = 'memory'
          AND valid_until IS NULL
          AND subtype IS NOT NULL
          AND subtype != 'context'
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        NeuronContext(
            subtype=row["subtype"],
            title=row["title"],
            tags=json.loads(row["tags"]) if row["tags"] else [],
        )
        for row in rows
    ]


def list_active_nodes(
    conn: sqlite3.Connection,
    *,
    kind: str | None = None,
    valid_at: str | None = None,
) -> list[NeuronRecord]:
    """Return neurons valid at `valid_at` (default: now)."""
    at = valid_at or utc_now_iso()
    params: list[Any] = [at, at]
    kind_clause = ""
    if kind is not None:
        kind_clause = "AND kind = ?"
        params.append(kind)

    rows = conn.execute(
        f"""
        SELECT id, kind, subtype, title, content, valid_from, valid_until, session_id
        FROM nodes
        WHERE valid_from <= ?
          AND (valid_until IS NULL OR valid_until > ?)
          {kind_clause}
        ORDER BY created_at ASC
        """,
        params,
    ).fetchall()
    return [_row_to_record(row) for row in rows]
