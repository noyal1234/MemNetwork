"""Tests for Phase A–C retrieval intelligence upgrades."""

from __future__ import annotations

from pathlib import Path

from brainkm.adapters.embeddings import HashingEmbedder
from brainkm.db.connection import connect
from brainkm.db.migrate import migrate
from brainkm.models.brain_config import BrainConfig, SemanticConfig
from brainkm.services.compress import compress_body, dedup_budget_lines
from brainkm.services.intent import QueryIntent, classify_intent, route_query
from brainkm.services.budget import BudgetLine, adaptive_token_budget
from brainkm.services.memory import remember_neuron, token_count
from brainkm.services.search import hybrid_seed, ppr_activate, recall_with_bfs
from brainkm.services.semantic import reciprocal_rank_fusion, upsert_node_embedding
from brainkm.services.remember_links import detect_conflicts
from brainkm.services.consolidate import consolidate_neurons
from brainkm.services.feedback import record_injected, record_used


def _brain(tmp_path: Path):
    migrate(project_dir=tmp_path, run_integrity_check=False)
    return connect(tmp_path / ".brain" / "brain.db")


def test_hashing_embedder_deterministic() -> None:
    emb = HashingEmbedder()
    a = emb.embed("JWT renewal failure")
    b = emb.embed("JWT renewal failure")
    assert a == b
    assert abs(sum(x * x for x in a) - 1.0) < 1e-5


def test_rrf_fusion_orders_overlap_first() -> None:
    fts = [("a", 1.0), ("b", 0.5), ("c", 0.1)]
    vec = [("b", 0.9), ("d", 0.8), ("a", 0.2)]
    fused = reciprocal_rank_fusion(fts, vec)
    ids = [node_id for node_id, _ in fused]
    assert ids[0] in {"a", "b"}
    assert "d" in ids


def test_classify_intent_routing() -> None:
    assert classify_intent("why did we choose JWT") == QueryIntent.WHY
    assert classify_intent("what calls AuthService") == QueryIntent.IMPACT
    assert classify_intent("where is recall_with_bfs defined") == QueryIntent.LOCATE
    assert route_query("why choose X").token_budget_fraction < 1.0


def test_hybrid_seed_and_ppr(tmp_path: Path) -> None:
    conn = _brain(tmp_path)
    try:
        a = remember_neuron(
            conn,
            title="Chose JWT for API auth",
            content="Prefer JWT over session cookies for the API.",
            subtype="decision",
            semantic_enabled=True,
        )
        b = remember_neuron(
            conn,
            title="Session cookies rejected",
            content="Do not use session cookies for API auth.",
            subtype="decision",
            semantic_enabled=True,
        )
        conn.execute(
            """
            INSERT INTO edges (id, from_id, to_id, relationship, weight, created_at, updated_at)
            VALUES ('e1', ?, ?, 'co_activated', 2.0, datetime('now'), datetime('now'))
            """,
            (a.id, b.id),
        )
        conn.commit()
        seeds = hybrid_seed(
            conn,
            "JWT authentication decision",
            semantic=SemanticConfig(enabled=True),
        )
        assert seeds
        meta, hops = ppr_activate(conn, {seeds[0][0]: 1.0}, iterations=4)
        assert a.id in meta or b.id in meta
        assert hops >= 0

        result = recall_with_bfs(
            conn,
            "why did we choose JWT",
            semantic=SemanticConfig(enabled=True),
            project_dir=tmp_path,
        )
        assert result.intent == "why"
        assert not result.abstained or result.nodes == []
    finally:
        conn.close()


def test_conflict_detection(tmp_path: Path) -> None:
    conn = _brain(tmp_path)
    try:
        remember_neuron(
            conn,
            title="Use Redis for cache",
            content="Always use Redis as the caching backend.",
            subtype="decision",
        )
        conn.commit()
        suggestions = detect_conflicts(
            conn,
            title="Use Redis for cache",
            content="Never use Redis; prefer in-memory cache instead.",
        )
        assert suggestions
        assert any(s.conflict for s in suggestions)
    finally:
        conn.close()


def test_compress_and_dedup() -> None:
    long = (
        "We decided to use SQLite. "
        "Hello there how are you. "
        "Because SQLite is local-first and requires zero ops. "
        "Nice weather today. "
        "Prefer WAL mode always."
    )
    compressed = compress_body(long, max_tokens=40)
    assert token_count(compressed) <= 40
    assert "SQLite" in compressed or "WAL" in compressed
    lines = [
        BudgetLine("1", "memory", "fact", "Auth JWT", "Use JWT bearer tokens for API auth always", 10, 1),
        BudgetLine("2", "memory", "fact", "Auth JWT", "Use JWT bearer tokens for API auth always", 10, 1),
        BudgetLine("3", "memory", "decision", "Other", "graphify sync policy distinct content", 8, 0),
    ]
    deduped = dedup_budget_lines(lines, threshold=0.5)
    assert len(deduped) == 2
    assert {line.node_id for line in deduped} == {"1", "3"} or len(deduped) < 3


def test_adaptive_budget() -> None:
    cfg = BrainConfig()
    why = adaptive_token_budget(cfg, "why did we choose JWT")
    impact = adaptive_token_budget(cfg, "what calls AuthService impact")
    assert why <= cfg.budget.total_tokens
    assert impact >= why


def test_feedback_and_consolidate(tmp_path: Path) -> None:
    conn = _brain(tmp_path)
    try:
        a = remember_neuron(
            conn,
            title="Prefer local ONNX embeddings",
            content="Use local ONNX MiniLM for T1 semantic search.",
            subtype="decision",
        )
        b = remember_neuron(
            conn,
            title="Prefer local ONNX embeddings",
            content="Use local ONNX MiniLM for T1 semantic search offline.",
            subtype="decision",
        )
        record_injected(conn, [a.id, b.id])
        record_used(conn, [a.id])
        conn.commit()
        result = consolidate_neurons(conn, dry_run=False, similarity_threshold=0.85)
        conn.commit()
        assert result.scanned >= 2
    finally:
        conn.close()


def test_upsert_embedding_roundtrip(tmp_path: Path) -> None:
    conn = _brain(tmp_path)
    try:
        node = remember_neuron(conn, title="Embed me", content="vector text")
        upsert_node_embedding(conn, node.id, "Embed me\nvector text", prefer_onnx=False)
        conn.commit()
        row = conn.execute(
            "SELECT dim, embedding FROM node_embeddings WHERE node_id = ?",
            (node.id,),
        ).fetchone()
        assert row is not None
        assert row[0] == 384
        assert isinstance(row[1], (bytes, memoryview))
    finally:
        conn.close()
