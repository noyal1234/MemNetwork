"""Tests for Common Memory Axes (CMA) and LongMemEval footnote suites."""

from __future__ import annotations

import json
from pathlib import Path

from brainkm.services.cma_bench import (
    format_cma_summary,
    render_cma_scorecard_markdown,
    run_cma_suite,
)
from brainkm.services.longmemeval_bench import (
    format_longmemeval_summary,
    load_longmemeval_questions,
    run_longmemeval_suite,
    stratify_sample,
)
from brainkm.services.scorecard_bench import run_scorecard_suite


def test_cma_suite_passes_floors(tmp_path: Path) -> None:
    result = run_cma_suite(tmp_path / ".brain" / "brain.db")
    assert result.suite == "cma"
    assert result.total >= 50
    assert result.passed == result.total
    summary = format_cma_summary(result)
    assert "micro=" in summary
    assert "pack=" in summary
    assert "baselines:" in summary
    assert "hard_slice_lift:" in summary
    # v3 hard slice should beat BM25
    hard = next(c for c in result.cases if c.name == "baseline/hard_slice_brain_vs_bm25")
    assert hard.passed


def test_cma_scorecard_markdown_render(tmp_path: Path) -> None:
    result = run_cma_suite(tmp_path / "x")
    md = render_cma_scorecard_markdown(
        result,
        version="0.4.1",
        commit="abc1234",
        machine="test",
        semantic=False,
    )
    assert "Common Memory Axes" in md
    assert "0.4.1" in md
    assert "abc1234" in md


def test_scorecard_structure_requires_neighbors(tmp_path: Path) -> None:
    result = run_scorecard_suite(tmp_path / ".brain" / "brain.db")
    assert result.total >= 8  # 4 decision + 4 structure
    assert result.passed == result.total
    structure = [c for c in result.cases if c.name.startswith("structure:")]
    assert len(structure) >= 4
    assert all(c.passed for c in structure)


def test_longmemeval_skips_without_dataset(tmp_path: Path) -> None:
    result = run_longmemeval_suite(tmp_path / "db", dataset=tmp_path / "missing.json")
    assert result.total == 1
    assert result.passed == 1
    assert result.cases[0].name == "skipped/no_dataset"
    assert "CMA" in format_longmemeval_summary(result) or "SKIPPED" in format_longmemeval_summary(
        result
    )


def test_longmemeval_loader_and_stratify(tmp_path: Path) -> None:
    payload = [
        {
            "question_id": "q1",
            "question_type": "temporal-reasoning",
            "question": "when did we change the TTL",
            "answer_session_ids": ["s_gold"],
            "haystack_session_ids": ["s_gold", "s_other"],
            "haystack_sessions": [
                [{"role": "user", "content": "TTL is now 15 minutes"}],
                [{"role": "user", "content": "unrelated pizza toppings"}],
            ],
        },
        {
            "question_id": "q2",
            "question_type": "temporal-reasoning",
            "question": "second temporal",
            "answer_session_ids": ["s2"],
            "haystack_session_ids": ["s2"],
            "haystack_sessions": [[{"role": "user", "content": "hello"}]],
        },
        {
            "question_id": "q3",
            "question_type": "knowledge-update",
            "question": "updated budget",
            "answer_session_ids": ["s3"],
            "haystack_session_ids": ["s3"],
            "haystack_sessions": [[{"role": "user", "content": "budget 1500"}]],
        },
    ]
    path = tmp_path / "lme.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    questions = load_longmemeval_questions(path)
    assert len(questions) == 3
    sampled = stratify_sample(questions, 1)
    assert len(sampled) == 2  # one per type
    result = run_longmemeval_suite(tmp_path / "db", dataset=path, stratify=1)
    assert result.suite == "longmemeval"
    names = {c.name for c in result.cases}
    assert "aggregate/recall_at_5" in names
    assert "aggregate/recall_at_budget" in names
    assert "aggregate/mean_pack_tokens" in names
    assert result.passed == result.total
    # Dual-grain default mode label
    r5 = next(c for c in result.cases if c.name == "aggregate/recall_at_5")
    assert "fts-blob" in r5.detail
