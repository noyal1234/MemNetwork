"""One-time backfills for about_* and supersedes edges."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from brainkm.services.memory import supersede_neuron
from brainkm.services.neuron_index import index_neuron_links

_TOKEN = re.compile(r"[a-z0-9]+", re.I)


@dataclass(frozen=True)
class BackfillLinksResult:
    scanned: int
    linked: int
    edges_added: int


@dataclass(frozen=True)
class BackfillSupersedesResult:
    scanned: int
    pairs: int
    edges_added: int
    dry_run: bool = False
    preview: list[tuple[str, str]] = field(default_factory=list)


def backfill_neuron_links(
    conn: sqlite3.Connection,
    *,
    limit: int = 500,
) -> BackfillLinksResult:
    """Re-run path/symbol indexing for active memory neurons missing about_* edges."""
    rows = conn.execute(
        """
        SELECT n.id, n.title, n.content, n.tags, n.kind
        FROM nodes n
        WHERE n.valid_until IS NULL
          AND n.kind IN ('memory', 'procedure')
          AND NOT EXISTS (
            SELECT 1 FROM edges e
            WHERE e.from_id = n.id
              AND e.relationship IN ('about_file', 'about_symbol')
          )
        ORDER BY n.updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    scanned = 0
    linked = 0
    edges_before = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE relationship IN ('about_file', 'about_symbol')"
    ).fetchone()[0]

    for row in rows:
        scanned += 1
        tags: list[str] = []
        if row["tags"]:
            import json

            try:
                raw = json.loads(row["tags"]) if isinstance(row["tags"], str) else row["tags"]
                tags = list(raw) if isinstance(raw, list) else []
            except (json.JSONDecodeError, TypeError):
                tags = []
        code_ids = index_neuron_links(
            conn,
            row["id"],
            title=row["title"] or "",
            content=row["content"] or "",
            tags=tags,
            kind=row["kind"] or "memory",
        )
        if code_ids:
            linked += 1

    edges_after = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE relationship IN ('about_file', 'about_symbol')"
    ).fetchone()[0]
    return BackfillLinksResult(
        scanned=scanned,
        linked=linked,
        edges_added=max(0, int(edges_after) - int(edges_before)),
    )


def _title_tokens(title: str) -> set[str]:
    return {t.lower() for t in _TOKEN.findall(title) if len(t) > 2}


def _conflict_allows_supersede(
    conn: sqlite3.Connection,
    *,
    new_id: str,
    old_id: str,
    new_title: str,
    new_content: str,
) -> bool:
    """Require detect_conflicts to surface old_id before archiving an active neuron."""
    from brainkm.services.remember_links import detect_conflicts

    # Confirm a real conflict/near-dup signal — shared title tokens alone
    # must not archive live decisions.
    suggestions = detect_conflicts(
        conn,
        title=new_title,
        content=new_content,
        exclude_id=new_id,
        similarity_threshold=0.65,
    )
    return any(s.node_id == old_id and (s.conflict or s.similarity >= 0.9) for s in suggestions)


def backfill_supersedes(
    conn: sqlite3.Connection,
    *,
    limit: int = 200,
    min_token_overlap: float = 0.55,
    dry_run: bool = False,
    require_conflict: bool = True,
) -> BackfillSupersedesResult:
    """Chain near-duplicate decision neurons by temporal order (newer supersedes older).

    Idempotent: skips pairs that already have a supersedes edge.
    When ``require_conflict`` is True (default), active older neurons are only
    archived when ``detect_conflicts`` also flags the pair — token Jaccard alone
    is not enough to soft-delete live decisions.
    """
    rows = conn.execute(
        """
        SELECT id, title, content, created_at, updated_at, valid_until
        FROM nodes
        WHERE kind = 'memory' AND subtype = 'decision'
        ORDER BY COALESCE(updated_at, created_at) ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    scanned = len(rows)
    pairs = 0
    preview: list[tuple[str, str]] = []
    edges_before = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE relationship = 'supersedes'"
    ).fetchone()[0]

    by_row: list[tuple[str, set[str], str | None, str, str]] = [
        (
            row["id"],
            _title_tokens(row["title"] or ""),
            row["valid_until"],
            row["title"] or "",
            row["content"] or "",
        )
        for row in rows
    ]

    for i, (old_id, old_tok, old_until, _old_title, _old_content) in enumerate(by_row):
        if not old_tok:
            continue
        best: tuple[str, float, str, str] | None = None
        for new_id, new_tok, new_until, new_title, new_content in by_row[i + 1 :]:
            if new_until is not None:
                continue  # prefer active replacement
            if not new_tok:
                continue
            overlap = len(old_tok & new_tok) / max(1, len(old_tok | new_tok))
            if overlap < min_token_overlap:
                continue
            if best is None or overlap > best[1]:
                best = (new_id, overlap, new_title, new_content)
        if best is None:
            continue
        new_id, _overlap, new_title, new_content = best
        exists = conn.execute(
            """
            SELECT 1 FROM edges
            WHERE from_id = ? AND to_id = ? AND relationship = 'supersedes'
            """,
            (new_id, old_id),
        ).fetchone()
        if exists:
            continue

        # Active older neurons need a conflict/near-dup signal before archive.
        if old_until is None and require_conflict:
            if not _conflict_allows_supersede(
                conn,
                new_id=new_id,
                old_id=old_id,
                new_title=new_title,
                new_content=new_content,
            ):
                continue

        preview.append((new_id, old_id))
        if dry_run:
            pairs += 1
            continue

        if old_until is None:
            try:
                supersede_neuron(conn, old_id, replacement_id=new_id)
            except ValueError:
                continue
        else:
            from brainkm.services.audit import utc_now_iso
            from brainkm.services.memory import new_ulid

            now = utc_now_iso()
            conn.execute(
                """
                INSERT OR IGNORE INTO edges
                  (id, from_id, to_id, relationship, weight, created_at, updated_at)
                VALUES (?, ?, ?, 'supersedes', 1.0, ?, ?)
                """,
                (new_ulid(), new_id, old_id, now, now),
            )
        pairs += 1

    edges_after = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE relationship = 'supersedes'"
    ).fetchone()[0]
    return BackfillSupersedesResult(
        scanned=scanned,
        pairs=pairs,
        edges_added=0 if dry_run else max(0, int(edges_after) - int(edges_before)),
        dry_run=dry_run,
        preview=preview,
    )
