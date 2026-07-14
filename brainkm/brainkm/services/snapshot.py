"""Frozen SessionStart injection snapshots — separate from live recall."""

from __future__ import annotations

import json
import sqlite3

from brainkm.logging_config import get_logger
from brainkm.models.brain_config import BrainConfig
from brainkm.models.snapshot import InjectionSnapshot, SnapshotNeuron
from brainkm.services.audit import utc_now_iso
from brainkm.services.channel_health import graph_available, graph_counts
from brainkm.services.memory import new_ulid, token_count
from brainkm.services.quality import passes_stored_neuron_gate

logger = get_logger("services.snapshot")


def _row_to_snapshot_neuron(row: sqlite3.Row) -> SnapshotNeuron:
    return SnapshotNeuron(
        node_id=row["id"],
        kind=row["kind"],
        subtype=row["subtype"],
        title=row["title"],
        content=row["content"],
        token_count=int(row["token_count"] or 0),
    )


def _fetch_neurons(
    conn: sqlite3.Connection,
    sql: str,
    params: tuple[object, ...] = (),
) -> list[SnapshotNeuron]:
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_snapshot_neuron(row) for row in rows]


def _hint_boost(title: str, content: str | None, context_hint: str) -> int:
    hint = context_hint.lower()
    text = f"{title} {(content or '')}".lower()
    tokens = [token for token in hint.split() if len(token) >= 4]
    return sum(1 for token in tokens if token in text)


def select_injection_neurons(
    conn: sqlite3.Connection,
    config: BrainConfig,
    *,
    context_hint: str | None = None,
) -> list[SnapshotNeuron]:
    """Select neurons for the SessionStart pack from live DB at snapshot time."""
    selected: list[SnapshotNeuron] = []
    seen: set[str] = set()
    budgets = config.budget.session_start

    def add_rows(rows: list[SnapshotNeuron], token_budget: int) -> None:
        used = 0
        for row in rows:
            if row.node_id in seen:
                continue
            if row.kind == "memory" and not passes_stored_neuron_gate(
                title=row.title,
                content=row.content,
            ):
                continue
            cost = row.token_count or token_count(f"{row.title}\n{row.content or ''}")
            if used + cost > token_budget and selected:
                break
            seen.add(row.node_id)
            selected.append(row)
            used += cost

    base_where = """
        FROM nodes
        WHERE valid_until IS NULL
          AND kind = 'memory'
    """

    add_rows(
        _fetch_neurons(
            conn,
            f"""
            SELECT id, kind, subtype, title, content, token_count
            {base_where} AND user_pinned = 1
            ORDER BY updated_at DESC
            """,
        ),
        budgets.pinned_rules,
    )

    add_rows(
        _fetch_neurons(
            conn,
            f"""
            SELECT id, kind, subtype, title, content, token_count
            {base_where} AND subtype = 'rule' AND user_pinned = 0
            ORDER BY use_count DESC, updated_at DESC
            LIMIT 20
            """,
        ),
        budgets.pinned_rules,
    )

    add_rows(
        _fetch_neurons(
            conn,
            f"""
            SELECT id, kind, subtype, title, content, token_count
            {base_where} AND subtype = 'decision'
            ORDER BY use_count DESC, updated_at DESC
            LIMIT 10
            """,
        ),
        budgets.pinned_rules,
    )

    add_rows(
        _fetch_neurons(
            conn,
            f"""
            SELECT id, kind, subtype, title, content, token_count
            {base_where} AND subtype = 'context'
            ORDER BY created_at DESC
            LIMIT 3
            """,
        ),
        budgets.session_status,
    )

    add_rows(
        _fetch_neurons(
            conn,
            """
            SELECT id, kind, subtype, title, content, token_count
            FROM nodes
            WHERE valid_until IS NULL
              AND kind = 'procedure'
            ORDER BY use_count DESC, updated_at DESC
            LIMIT 10
            """,
        ),
        budgets.procedure_stubs,
    )

    if context_hint:
        selected.sort(
            key=lambda neuron: _hint_boost(neuron.title, neuron.content, context_hint),
            reverse=True,
        )

    return selected


def _graph_status_line(conn: sqlite3.Connection) -> str | None:
    if not graph_available(conn):
        return None
    node_count, edge_count = graph_counts(conn)
    return (
        f"Code graph: {node_count} nodes / {edge_count} edges. "
        "For call/import/flow questions consult traverse or context_pack with a symbol, "
        "then verify in source before editing."
    )


def render_injection_pack(
    neurons: list[SnapshotNeuron],
    *,
    graph_status: str | None = None,
) -> str:
    if not neurons:
        lines = [
            "# MemNetwork brain (frozen snapshot)",
            "",
            "No pinned rules or context neurons yet.",
            "",
        ]
        if graph_status:
            lines.extend([graph_status, ""])
        return "\n".join(lines)

    sections: dict[str, list[SnapshotNeuron]] = {
        "Pinned": [],
        "Rules & decisions": [],
        "Context": [],
        "Procedures": [],
    }
    for neuron in neurons:
        if neuron.kind == "procedure":
            sections["Procedures"].append(neuron)
        elif neuron.subtype == "context":
            sections["Context"].append(neuron)
        elif neuron.subtype in {"rule", "decision"}:
            sections["Rules & decisions"].append(neuron)
        else:
            sections["Pinned"].append(neuron)

    lines = ["# MemNetwork brain (frozen snapshot)", ""]
    if graph_status:
        lines.extend([graph_status, ""])
    for heading, items in sections.items():
        if not items:
            continue
        lines.append(f"## {heading}")
        lines.append("")
        for item in items:
            body = (item.content or "").strip()
            if body:
                lines.append(f"- **{item.title}** ({item.subtype or item.kind}): {body}")
            else:
                lines.append(f"- **{item.title}** ({item.subtype or item.kind})")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def get_frozen_snapshot(
    conn: sqlite3.Connection,
    session_id: str,
) -> InjectionSnapshot | None:
    row = conn.execute(
        """
        SELECT session_id, pack_text, neuron_ids, token_count, frozen, created_at
        FROM session_snapshots
        WHERE session_id = ?
        """,
        (session_id,),
    ).fetchone()
    if row is None:
        return None

    neuron_ids = tuple(json.loads(row["neuron_ids"]))
    return InjectionSnapshot(
        session_id=row["session_id"],
        neuron_ids=neuron_ids,
        pack_text=row["pack_text"],
        token_count=int(row["token_count"]),
        created_at=row["created_at"],
        frozen=bool(row["frozen"]),
    )


def save_frozen_snapshot(
    conn: sqlite3.Connection,
    snapshot: InjectionSnapshot,
) -> None:
    conn.execute(
        """
        INSERT INTO session_snapshots (
          session_id, pack_text, neuron_ids, token_count, frozen, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO NOTHING
        """,
        (
            snapshot.session_id,
            snapshot.pack_text,
            json.dumps(list(snapshot.neuron_ids), separators=(",", ":")),
            snapshot.token_count,
            1 if snapshot.frozen else 0,
            snapshot.created_at,
        ),
    )


def build_frozen_snapshot(
    conn: sqlite3.Connection,
    session_id: str,
    config: BrainConfig,
    *,
    force: bool = False,
    context_hint: str | None = None,
) -> InjectionSnapshot:
    """Build or return the frozen injection snapshot for a session."""
    graph_status = _graph_status_line(conn)

    if not config.injection.frozen_snapshot:
        neurons = select_injection_neurons(conn, config, context_hint=context_hint)
        pack_text = render_injection_pack(neurons, graph_status=graph_status)
        now = utc_now_iso()
        return InjectionSnapshot(
            session_id=session_id,
            neuron_ids=tuple(n.node_id for n in neurons),
            pack_text=pack_text,
            token_count=token_count(pack_text),
            created_at=now,
            frozen=False,
        )

    existing = get_frozen_snapshot(conn, session_id)
    if existing is not None and not force:
        logger.info(
            "hook=SessionStart session_id=%s snapshot=reused neurons=%d",
            session_id,
            len(existing.neuron_ids),
        )
        return existing

    neurons = select_injection_neurons(conn, config, context_hint=context_hint)
    pack_text = render_injection_pack(neurons, graph_status=graph_status)
    now = utc_now_iso()
    snapshot = InjectionSnapshot(
        session_id=session_id,
        neuron_ids=tuple(n.node_id for n in neurons),
        pack_text=pack_text,
        token_count=token_count(pack_text),
        created_at=now,
        frozen=True,
    )
    save_frozen_snapshot(conn, snapshot)
    conn.commit()
    logger.info(
        "hook=SessionStart session_id=%s snapshot=created neurons=%d tokens=%d",
        session_id,
        len(snapshot.neuron_ids),
        snapshot.token_count,
    )
    return snapshot


def resolve_session_id(data: dict[str, object]) -> str:
    for key in ("session_id", "sessionId", "conversation_id", "conversationId"):
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value)
    generated = new_ulid()
    logger.warning("SessionStart missing session_id; generated %s", generated)
    return generated
