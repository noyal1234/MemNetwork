"""Tests for plan chunking, recall dedup, hooks, and bench runner."""

from __future__ import annotations

from pathlib import Path

from brainkm.adapters.plans import chunk_plan_file
from brainkm.db.connection import connect
from brainkm.models.brain_config import BrainConfig
from brainkm.models.distill import DistilledNeuron
from brainkm.services.bench_runner import run_abstention_suite
from brainkm.services.budget import classify_query_type, context_pack_slots
from brainkm.services.hooks import run_post_compact
from brainkm.services.memory import flush_use_counts
from brainkm.services.quality import passes_quality_gate
from brainkm.services.recall_dedup import deduped_session_chunks
from tests.conftest import insert_node


def test_chunk_plan_file_by_heading(tmp_path: Path) -> None:
    plan = tmp_path / "test.plan.md"
    plan.write_text(
        "# Title\n\nIntro\n\n## Architecture\n\nUse SQLite.\n\n## Hooks\n\nPreCompact handover.\n",
        encoding="utf-8",
    )
    sections = chunk_plan_file(plan)
    assert len(sections) == 2
    assert sections[0].heading == "Architecture"


def test_quality_gate_rejects_boilerplate() -> None:
    item = DistilledNeuron(subtype="fact", title="ok", body="short")
    assert passes_quality_gate(item) is False


def test_classify_query_type_code() -> None:
    assert classify_query_type("fix auth.py login") == "code"


def test_dynamic_budget_allocates_more_graph_for_code() -> None:
    cfg = BrainConfig()
    code_slots = context_pack_slots(cfg, "edit src/foo.py")
    general_slots = context_pack_slots(cfg, "project overview")
    assert code_slots["graph"] >= general_slots["graph"]


def test_recall_dedup_skips_covered_chunks(brain_db) -> None:
    conn = connect(brain_db)
    try:
        insert_node(conn, node_id="n1", title="JWT policy", content="token expiry rules")
        conn.execute(
            """
            INSERT INTO session_chunks (id, session_id, role, content, ts)
            VALUES ('c1', 's1', 'user', 'JWT policy discussion', datetime('now'))
            """
        )
        conn.execute(
            """
            INSERT INTO chunk_sources (chunk_id, neuron_id, distill_ts)
            VALUES ('c1', 'n1', datetime('now'))
            """
        )
        conn.commit()
        hits = deduped_session_chunks(conn, "JWT policy", {"n1"})
        assert hits == []
    finally:
        conn.close()


def test_flush_use_counts(brain_db) -> None:
    conn = connect(brain_db)
    try:
        insert_node(conn, node_id="used", title="used neuron", content="content")
        conn.commit()
        from brainkm.services.session_activity import get_session_activity

        get_session_activity().track("sess", ["used"])
        count = flush_use_counts(conn, "sess")
        conn.commit()
        row = conn.execute("SELECT use_count FROM nodes WHERE id = 'used'").fetchone()
        assert count == 1
        assert row[0] == 1
    finally:
        conn.close()


def test_post_compact_refreshes_snapshot(brain_db) -> None:
    conn = connect(brain_db)
    try:
        insert_node(
            conn,
            node_id="rule1",
            subtype="rule",
            title="Always checkpoint WAL",
            content="checkpoint before exit",
        )
        conn.commit()
    finally:
        conn.close()

    project_dir = brain_db.parent.parent
    payload = '{"session_id": "post-compact-test", "context_hint": "WAL checkpoint"}'
    result = run_post_compact(payload, project_dir=project_dir)
    assert result.skipped is False
    assert result.snapshot_neuron_ids


def test_bench_abstention_suite(brain_db) -> None:
    result = run_abstention_suite(brain_db)
    assert result.total >= 8
    assert result.pass_rate == 1.0
