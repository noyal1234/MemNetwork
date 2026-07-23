"""Tests for precision, staleness, scale, cost, hybrid chunking, off-domain gate."""

from __future__ import annotations

import json
from pathlib import Path

from brainkm.services.bench_adapters import (
    naive_title_scan_rank,
    score_ranked_sessions,
)
from brainkm.services.bench_runner import run_bench_suite
from brainkm.services.cost_bench import format_cost_summary, run_cost_suite
from brainkm.services.intent import is_off_domain_query
from brainkm.services.ir_metrics import (
    pack_noise_rate,
    precision_at_k,
    recall_at_budget,
    recall_at_k,
)
from brainkm.services.longmemeval_bench import (
    aggregate_ranked_to_sessions,
    chunk_session_text,
    filter_chunk_ids,
    fuse_session_fts_primary,
    session_id_from_chunk_id,
    stratify_sample,
)
from brainkm.services.scale_bench import run_scale_suite
from brainkm.services.staleness_bench import run_staleness_suite


def test_precision_at_k_basic() -> None:
    ranked = ["a", "b", "c", "d", "e"]
    assert precision_at_k(ranked, {"a", "x"}, 5) == 0.2
    assert precision_at_k(ranked, {"a"}, 1) == 1.0
    assert precision_at_k([], {"a"}, 5) == 0.0
    assert recall_at_k(ranked, {"a", "c"}, 5) == 1.0
    assert recall_at_budget(["gold", "noise"], {"gold"}) == 1.0
    assert pack_noise_rate(["gold", "noise"], {"gold"}) == 0.5


def test_chunk_session_and_aggregate() -> None:
    text = "word " * 400
    chunks = chunk_session_text(text, chunk_chars=100, overlap=20)
    assert len(chunks) > 1
    assert session_id_from_chunk_id("sessA__chunk_3") == "sessA"
    assert session_id_from_chunk_id("sessA") == "sessA"
    ranked = ["s1__chunk_0", "s2__chunk_1", "s1__chunk_2", "s3"]
    assert aggregate_ranked_to_sessions(ranked) == ["s1", "s2", "s3"]
    assert filter_chunk_ids(["s1", "s1__chunk_0", "s2"]) == ["s1", "s2"]
    fused = fuse_session_fts_primary(["a", "b", "c"], ["c", "b", "z"])
    assert fused == ["c", "b", "a"]


def test_stratify_sample_is_seeded() -> None:
    questions = [{"type": "a", "id": f"a{i}"} for i in range(20)] + [
        {"type": "b", "id": f"b{i}"} for i in range(20)
    ]
    s1 = [q["id"] for q in stratify_sample(questions, 5, seed=7)]
    s2 = [q["id"] for q in stratify_sample(questions, 5, seed=7)]
    s3 = [q["id"] for q in stratify_sample(questions, 5, seed=99)]
    assert s1 == s2
    assert s1 != s3


def test_off_domain_query_gate() -> None:
    assert is_off_domain_query("what is my neighbor pinecone's wifi password for the cabin")
    assert is_off_domain_query("is neo4j a good name for my dog")
    assert not is_off_domain_query("why did we defer neo4j for the project brain")


def test_naive_adapter_and_scores() -> None:
    titles = {"a": "JWT auth", "b": "pizza recipe"}
    contents = {"a": "jose middleware", "b": "tomato basil"}
    ranked = naive_title_scan_rank("jwt jose auth", titles, contents, limit=5)
    assert ranked[0] == "a"
    scores = score_ranked_sessions(ranked, {"a"})
    assert scores["r@5"] == 1.0
    assert scores["p@5"] > 0


def test_staleness_suite_passes(tmp_path: Path) -> None:
    result = run_staleness_suite(tmp_path / "db")
    assert result.suite == "staleness"
    assert result.passed == result.total
    assert any(c.name == "aggregate/supersede_top1" for c in result.cases)


def test_scale_suite_fast(tmp_path: Path) -> None:
    # Tiny sizes for unit speed
    result = run_scale_suite(tmp_path / "db", sizes=(50,), fast=True)
    assert result.suite == "scale"
    assert result.total >= 4
    assert any("recall_at_5" in c.name for c in result.cases)
    assert result.passed == result.total


def test_cost_suite(tmp_path: Path) -> None:
    result = run_cost_suite(tmp_path / "db")
    assert result.suite == "cost"
    assert result.passed == result.total
    summary = format_cost_summary(result)
    assert "injected/session" in summary
    assert "annual=" in summary


def test_retrieval_reports_precision(tmp_path: Path) -> None:
    result = run_bench_suite("retrieval", tmp_path / ".brain" / "brain.db")
    names = {c.name for c in result.cases}
    assert "precision_at_1" in names
    assert "precision_at_5" in names


def test_cma_theme_leak_gates(tmp_path: Path) -> None:
    result = run_bench_suite("cma", tmp_path / ".brain" / "brain.db")
    theme = [c for c in result.cases if "theme_leak" in c.name or c.name.startswith("theme")]
    ability = next(c for c in result.cases if c.name == "ability/theme_leak")
    assert ability.passed, ability.detail
    # Per-query theme leak cases must also pass (no longer report_only).
    query_cases = [
        c
        for c in result.cases
        if c.name.startswith("theme_leak/") or "theme_neo4j" in c.name or "pinecone" in c.name
    ]
    # CMA names queries as ability/id style in cases — find leaked= in details
    leak_cases = [c for c in result.cases if "leaked=" in c.detail]
    assert leak_cases, "expected theme_leak case details"
    assert all(c.passed for c in leak_cases), json.dumps(
        [{"n": c.name, "d": c.detail} for c in leak_cases if not c.passed]
    )
    _ = theme, query_cases


def test_longmemeval_chunked_fixture(tmp_path: Path) -> None:
    from brainkm.services.longmemeval_bench import run_longmemeval_suite

    payload = [
        {
            "question_id": "q1",
            "question_type": "knowledge-update",
            "question": "what is the TTL now",
            "answer_session_ids": ["s_gold"],
            "haystack_session_ids": ["s_gold", "s_other"],
            "haystack_sessions": [
                [{"role": "user", "content": "TTL is now 15 minutes for observations"}],
                [{"role": "user", "content": "unrelated pizza toppings forever"}],
            ],
        }
    ]
    path = tmp_path / "lme.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = run_longmemeval_suite(tmp_path / "db", dataset=path, stratify=1, adapters=True, seed=1)
    assert any(c.name == "aggregate/precision_at_5" for c in result.cases)
    assert any(c.name.startswith("adapter/") for c in result.cases)
    assert result.passed == result.total
