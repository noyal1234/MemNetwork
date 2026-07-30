"""V2 procedure promotion from co-activation signals."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass

from brainkm.models.brain_config import BrainConfig
from brainkm.services.memory import new_ulid, remember_neuron
from brainkm.services.search import resolve_node_ref


@dataclass(frozen=True)
class ProcedureItem:
    node_id: str
    title: str
    use_count: int


def list_procedure_nodes(conn: sqlite3.Connection, *, limit: int = 20) -> list[ProcedureItem]:
    """Active procedure neurons, most-used first (CLI/MCP surface — was zero exposure before).

    A wrong or stale procedure otherwise keeps re-injecting into every pack
    until it ages out on its own via ``archive_ignored_procedures``.
    """
    rows = conn.execute(
        """
        SELECT id, title, COALESCE(use_count, 0) AS use_count
        FROM nodes
        WHERE valid_until IS NULL AND kind = 'procedure'
        ORDER BY use_count DESC, updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        ProcedureItem(node_id=row["id"], title=row["title"], use_count=int(row["use_count"]))
        for row in rows
    ]

_INTERNAL_TOOLS = frozenset(
    {
        "remember",
        "recall",
        "context_pack",
        "traverse",
        "brain_stats",
        # Removed from MCP but may still appear in historical session windows
        "session_status",
        "forget",
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


def _procedure_key(tool_names: list[str], neuron_ids: list[str] | None = None) -> str:
    """Stable key for a tool chain.

    Keyed by ordered external tools only so the same Write→Shell sequence
    merges into one procedure (neuron-pair keys used to create dozens of
    near-duplicate Write→Shell neurons that polluted every pack).
    ``neuron_ids`` is accepted for call-site compatibility but ignored.
    """
    del neuron_ids  # lineage stays on spawned/distilled_from edges
    tools = "|".join(ordered_external_tools(tool_names))
    raw = f"tools::{tools}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _existing_procedure_id(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute(
        """
        SELECT id
        FROM nodes
        WHERE valid_until IS NULL AND kind = 'procedure' AND source = ?
        LIMIT 1
        """,
        (f"learning:proc:{key}",),
    ).fetchone()
    return str(row["id"]) if row is not None else None


def _bump_procedure_use(conn: sqlite3.Connection, node_id: str) -> None:
    conn.execute(
        """
        UPDATE nodes
        SET use_count = COALESCE(use_count, 0) + 1,
            updated_at = datetime('now')
        WHERE id = ? AND valid_until IS NULL
        """,
        (node_id,),
    )


def _existing_procedure(conn: sqlite3.Connection, key: str) -> bool:
    return _existing_procedure_id(conn, key) is not None


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


def _context_titles_for_procedure(titles: list[str]) -> list[str]:
    """Keep path/symbol-ish titles only — evergreen rules pollute pack overlap."""
    kept: list[str] = []
    for title in titles:
        text = (title or "").strip()
        if not text or len(text) > 80:
            continue
        if "/" in text or "\\" in text or re.search(r"\.\w{1,5}\b", text):
            kept.append(text)
            continue
        # Identifiers: snake_case, CamelCase, or short TitleCase nouns (Auth).
        if re.fullmatch(r"[A-Za-z_][\w.]{2,60}", text) and (
            "_" in text
            or any(c.isupper() for c in text[1:])
            or (text[0].isupper() and text[1:].islower() and " " not in text)
        ):
            kept.append(text)
    return kept[:5]


def _format_procedure_body(tools: list[str], context_titles: list[str]) -> str:
    steps = [f"{index + 1}. {name}" for index, name in enumerate(tools)]
    lines = [
        f"Tools: {' → '.join(tools)}",
        "",
        *steps,
    ]
    useful = _context_titles_for_procedure(context_titles)
    if useful:
        lines.extend(["", "Related context:"])
        lines.extend(f"- {title}" for title in useful)
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

    key = _procedure_key(tool_names)
    existing = _existing_procedure_id(conn, key)
    if existing is not None:
        _bump_procedure_use(conn, existing)
        # Still link new co-activated endpoints for lineage.
        for target in neuron_ids:
            conn.execute(
                """
                INSERT OR IGNORE INTO edges (id, from_id, to_id, relationship, weight, created_at,
                    updated_at)
                VALUES (?, ?, ?, 'spawned', 1.0, datetime('now'), datetime('now'))
                """,
                (new_ulid(), existing, target),
            )
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
            INSERT OR IGNORE INTO edges (id, from_id, to_id, relationship, weight, created_at,
                updated_at)
            VALUES (?, ?, ?, 'spawned', 1.0, datetime('now'), datetime('now'))
            """,
            (new_ulid(), from_id, target),
        )
        # Prefer high use_count sources; still link all for lineage.
        conn.execute(
            """
            INSERT OR IGNORE INTO edges (id, from_id, to_id, relationship, weight, created_at,
                updated_at)
            VALUES (?, ?, ?, 'distilled_from', 0.9, datetime('now'), datetime('now'))
            """,
            (new_ulid(), from_id, target),
        )
    return record.id


def dedupe_tool_chain_procedures(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
) -> list[str]:
    """Soft-archive duplicate tool_chain titles; keep highest use_count per title.

    Cleans historical Write→Shell spam created under the old neuron-pair key.
    """
    from brainkm.services.memory import forget_neuron

    rows = conn.execute(
        """
        SELECT id, title, COALESCE(use_count, 0) AS use_count, created_at
        FROM nodes
        WHERE valid_until IS NULL
          AND kind = 'procedure'
          AND subtype = 'tool_chain'
        ORDER BY title COLLATE NOCASE ASC, use_count DESC, created_at ASC
        """
    ).fetchall()
    kept_titles: set[str] = set()
    archived: list[str] = []
    for row in rows:
        title_key = " ".join((row["title"] or "").casefold().split())
        if not title_key:
            continue
        if title_key in kept_titles:
            archived.append(str(row["id"]))
            if not dry_run:
                forget_neuron(
                    conn,
                    str(row["id"]),
                    reason="hygiene: duplicate tool_chain title",
                )
            continue
        kept_titles.add(title_key)
    return archived


def check_and_promote(
    conn: sqlite3.Connection,
    session_id: str | None,
    *,
    config: BrainConfig,
) -> list[str]:
    from brainkm.services.learning import load_recent_neuron_ids, load_recent_tool_names

    if not session_id:
        return []

    learning = config.learning
    tool_names = load_recent_tool_names(
        conn,
        session_id,
        limit=learning.session_window_size,
    )
    session_neuron_ids = set(
        load_recent_neuron_ids(
            conn,
            session_id,
            limit=learning.session_window_size,
        )
    )
    if len(session_neuron_ids) < 2 or len(ordered_external_tools(tool_names)) < 2:
        return []

    promoted: list[str] = []
    for first, second in find_promotable_pairs(
        conn,
        threshold=learning.co_activation_threshold,
        session_neuron_ids=session_neuron_ids,
    ):
        # Skip invalid/archived references quickly.
        if resolve_node_ref(conn, first) is None or resolve_node_ref(conn, second) is None:
            continue
        if _pair_blocked_by_ignore(conn, first, second, learning=learning):
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


def _pair_blocked_by_ignore(
    conn: sqlite3.Connection,
    first: str,
    second: str,
    *,
    learning: object,
) -> bool:
    from brainkm.models.brain_config import LearningConfig
    from brainkm.services.feedback import ignore_rate

    cfg = learning if isinstance(learning, LearningConfig) else LearningConfig()
    for node_id in (first, second):
        rate, injected = ignore_rate(
            conn,
            node_id,
            half_life_days=cfg.promote_ignore_half_life_days,
        )
        if (
            injected >= cfg.promote_min_injected_count
            and rate > cfg.promote_max_ignore_rate
        ):
            return True
    return False

def archive_ignored_procedures(
    conn: sqlite3.Connection,
    *,
    max_ignore_rate: float = 0.5,
    min_injected_count: int = 5,
    half_life_days: int = 60,
    dry_run: bool = False,
) -> list[str]:
    """Soft-archive procedures with high effective ignore rate (stricter sample floor)."""
    from brainkm.services.feedback import ignore_rate
    from brainkm.services.memory import forget_neuron

    rows = conn.execute(
        """
        SELECT id
        FROM nodes
        WHERE valid_until IS NULL
          AND kind = 'procedure'
        """
    ).fetchall()
    archived: list[str] = []
    for row in rows:
        node_id = str(row["id"])
        rate, injected = ignore_rate(conn, node_id, half_life_days=half_life_days)
        if injected < min_injected_count or rate <= max_ignore_rate:
            continue
        archived.append(node_id)
        if not dry_run:
            forget_neuron(
                conn,
                node_id,
                reason="hygiene: procedure ignored above archive threshold",
            )
    return archived