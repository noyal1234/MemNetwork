"""Memory decay hygiene and offline consolidation ("sleep-time" pass)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from brainkm.adapters.embeddings import cosine_similarity, get_embedder
from brainkm.services.compress import compress_body
from brainkm.services.memory import forget_neuron, remember_neuron, supersede_neuron
from brainkm.services.quality import passes_stored_neuron_gate


@dataclass(frozen=True)
class DecayResult:
    scanned: int
    archived: int
    archived_ids: list[str]


@dataclass(frozen=True)
class ConsolidateResult:
    scanned: int
    merged: int
    archived: int
    new_ids: list[str]


def decay_unused_neurons(
    conn: sqlite3.Connection,
    *,
    unused_days: int = 90,
    dry_run: bool = False,
    limit: int | None = None,
) -> DecayResult:
    """Soft-archive memory neurons unused past the horizon (and low use_count)."""
    cutoff = (datetime.now(UTC) - timedelta(days=unused_days)).isoformat()
    sql = """
        SELECT id FROM nodes
        WHERE kind = 'memory'
          AND valid_until IS NULL
          AND user_pinned = 0
          AND COALESCE(use_count, 0) = 0
          AND updated_at < ?
        ORDER BY updated_at ASC
    """
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql, (cutoff,)).fetchall()
    archived: list[str] = []
    for (node_id,) in rows:
        if dry_run:
            archived.append(node_id)
            continue
        forget_neuron(conn, node_id, reason="decay_unused")
        archived.append(node_id)
    return DecayResult(scanned=len(rows), archived=len(archived), archived_ids=archived)


def consolidate_neurons(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
    similarity_threshold: float = 0.9,
    limit: int = 200,
) -> ConsolidateResult:
    """Merge near-duplicate memory neurons; roll chains into a denser fact."""
    rows = conn.execute(
        """
        SELECT id, title, content, subtype, confidence
        FROM nodes
        WHERE kind = 'memory' AND valid_until IS NULL
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    embedder = get_embedder(prefer_onnx=False)
    vectors = [
        (row[0], row[1], row[2] or "", row[3], float(row[4] or 1.0), embedder.embed(f"{row[1]}\n{row[2] or ''}"))
        for row in rows
    ]

    used: set[str] = set()
    merged = 0
    archived = 0
    new_ids: list[str] = []

    for i, (id_a, title_a, content_a, subtype_a, conf_a, vec_a) in enumerate(vectors):
        if id_a in used:
            continue
        cluster = [(id_a, title_a, content_a, subtype_a, conf_a)]
        for j in range(i + 1, len(vectors)):
            id_b, title_b, content_b, subtype_b, conf_b, vec_b = vectors[j]
            if id_b in used:
                continue
            if cosine_similarity(vec_a, vec_b) >= similarity_threshold:
                cluster.append((id_b, title_b, content_b, subtype_b, conf_b))
                used.add(id_b)
        if len(cluster) < 2:
            continue
        used.add(id_a)
        # Keep highest confidence as title seed; compress combined body.
        cluster.sort(key=lambda item: item[4], reverse=True)
        title = cluster[0][1]
        subtype = cluster[0][3] or "fact"
        combined = "\n".join(f"- {c[1]}: {c[2]}" for c in cluster)
        body = compress_body(combined, max_tokens=160)
        if not passes_stored_neuron_gate(title=title, content=body):
            continue
        if dry_run:
            merged += 1
            archived += len(cluster)
            continue
        keep_id = cluster[0][0]
        new_record = remember_neuron(
            conn,
            title=title,
            content=body,
            subtype=subtype,
            source="consolidate",
            confidence=min(1.0, cluster[0][4] + 0.05),
            compress=False,
        )
        new_ids.append(new_record.id)
        for old_id, *_ in cluster:
            try:
                supersede_neuron(conn, old_id, replacement=new_record)
                archived += 1
            except ValueError:
                forget_neuron(conn, old_id, reason="consolidate")
                archived += 1
        _ = keep_id
        merged += 1

    return ConsolidateResult(
        scanned=len(rows),
        merged=merged,
        archived=archived,
        new_ids=new_ids,
    )
