"""Hybrid semantic retrieval: vector search + Reciprocal Rank Fusion with FTS."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from brainkm.adapters.embeddings import (
    cosine_similarity,
    get_embedder,
    pack_embedding,
    unpack_embedding,
)
from brainkm.logging_config import get_logger

logger = get_logger("services.semantic")

RRF_K = 60


def upsert_node_embedding(
    conn: sqlite3.Connection,
    node_id: str,
    text: str,
    *,
    prefer_onnx: bool = True,
) -> None:
    """Embed text and store under node_id. No-op when table missing."""
    if not _embeddings_table_exists(conn):
        return
    embedder = get_embedder(prefer_onnx=prefer_onnx)
    vec = embedder.embed(text)
    blob = pack_embedding(vec)
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """
        INSERT INTO node_embeddings (node_id, model, dim, embedding, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(node_id) DO UPDATE SET
          model = excluded.model,
          dim = excluded.dim,
          embedding = excluded.embedding,
          updated_at = excluded.updated_at
        """,
        (node_id, embedder.model_id, embedder.dim, blob, now),
    )


def embed_neuron_if_enabled(
    conn: sqlite3.Connection,
    node_id: str,
    *,
    title: str,
    content: str | None,
    semantic_enabled: bool,
) -> None:
    if not semantic_enabled:
        return
    text = f"{title}\n{content or ''}".strip()
    if not text:
        return
    try:
        upsert_node_embedding(conn, node_id, text)
    except Exception:  # noqa: BLE001 — never fail writes on embed errors
        logger.debug("embedding upsert failed for %s", node_id, exc_info=True)


def vector_search_nodes(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 20,
    prefer_onnx: bool = True,
) -> list[tuple[str, float]]:
    """Return (node_id, cosine_similarity) for active nodes with embeddings."""
    if not _embeddings_table_exists(conn):
        return []
    embedder = get_embedder(prefer_onnx=prefer_onnx)
    qvec = embedder.embed(query)
    rows = conn.execute(
        """
        SELECT e.node_id, e.embedding
        FROM node_embeddings e
        JOIN nodes n ON n.id = e.node_id
        WHERE n.valid_until IS NULL
        """
    ).fetchall()
    scored: list[tuple[str, float]] = []
    for node_id, blob in rows:
        vec = unpack_embedding(blob)
        if len(vec) != len(qvec):
            continue
        scored.append((node_id, cosine_similarity(qvec, vec)))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:limit]


def reciprocal_rank_fusion(
    *rankings: list[tuple[str, float]],
    k: int = RRF_K,
) -> list[tuple[str, float]]:
    """Fuse multiple (id, score) lists via RRF. Score values are ignored; rank matters."""
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, (node_id, _) in enumerate(ranking, start=1):
            fused[node_id] = fused.get(node_id, 0.0) + 1.0 / (k + rank)
    return sorted(fused.items(), key=lambda item: item[1], reverse=True)


def try_load_sqlite_vec(conn: sqlite3.Connection) -> bool:
    """Attempt to load sqlite-vec extension; return True if available."""
    try:
        import sqlite_vec  # type: ignore[import-untyped]
    except ImportError:
        return False
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except Exception:  # noqa: BLE001
        logger.debug("sqlite-vec load failed", exc_info=True)
        return False


def backfill_embeddings(
    conn: sqlite3.Connection,
    *,
    limit: int | None = None,
    prefer_onnx: bool = True,
) -> int:
    """Embed active memory neurons missing from node_embeddings. Returns count."""
    if not _embeddings_table_exists(conn):
        return 0
    sql = """
        SELECT n.id, n.title, n.content
        FROM nodes n
        LEFT JOIN node_embeddings e ON e.node_id = n.id
        WHERE n.valid_until IS NULL
          AND n.kind = 'memory'
          AND e.node_id IS NULL
        ORDER BY n.updated_at DESC
    """
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql).fetchall()
    count = 0
    for node_id, title, content in rows:
        upsert_node_embedding(
            conn,
            node_id,
            f"{title}\n{content or ''}",
            prefer_onnx=prefer_onnx,
        )
        count += 1
    return count


def _embeddings_table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='node_embeddings'"
    ).fetchone()
    return row is not None


def semantic_ready(project_dir: Path | None = None) -> dict[str, bool | str]:
    """Diagnostics for doctors / TUI."""
    _ = project_dir
    has_onnx = False
    has_vec = False
    try:
        import onnxruntime  # noqa: F401

        has_onnx = True
    except ImportError:
        pass
    try:
        import sqlite_vec  # noqa: F401

        has_vec = True
    except ImportError:
        pass
    return {
        "onnxruntime": has_onnx,
        "sqlite_vec": has_vec,
        "fallback_embedder": "hashing-v1",
    }
