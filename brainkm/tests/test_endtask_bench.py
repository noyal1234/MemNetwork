"""Unit tests for end-task A/B helpers (no Cursor API)."""

from __future__ import annotations

from pathlib import Path

from brainkm.services.endtask_bench import (
    EndTaskReport,
    EndTaskRunRecord,
    build_groq_user_prompt,
    grade_checker,
    grade_regex,
    grade_task,
    load_endtask_fixture,
    plan_runs,
    render_endtask_markdown,
    seed_endtask_brain,
    select_tasks,
    write_ndjson,
)


def test_load_and_select_smoke_tasks() -> None:
    fixture = load_endtask_fixture()
    assert fixture["id"] == "endtask_v1"
    assert len(fixture["seed_neurons"]) >= 25
    tasks = select_tasks(fixture, smoke_only=True)
    assert len(tasks) == 5
    assert all(t["class"] == "knowledge" for t in tasks)
    knowledge = [t for t in fixture["tasks"] if t["class"] == "knowledge"]
    change = [t for t in fixture["tasks"] if t["class"] == "change"]
    assert len(knowledge) == 12
    assert len(change) == 8


def test_plan_runs_estimates() -> None:
    fixture = load_endtask_fixture()
    tasks = select_tasks(fixture, smoke_only=True)
    plan = plan_runs(fixture, tasks=tasks, repeats=3)
    assert plan.estimated_runs == 5 * 2 * 3
    assert plan.estimated_usd > 0


def test_grade_regex_and_checker(tmp_path: Path) -> None:
    ok = grade_regex(
        "Packs are hard-capped at 1500 tokens via budget.",
        ["1500", "(?i)token"],
    )
    assert ok.passed
    bad = grade_regex("no number here", ["1500"])
    assert not bad.passed

    (tmp_path / "marker.txt").write_text("ok", encoding="utf-8")
    chk = grade_checker(tmp_path, "test -f marker.txt")
    assert chk.passed
    chk_fail = grade_checker(tmp_path, "test -f missing.txt")
    assert not chk_fail.passed


def test_grade_task_knowledge() -> None:
    task = {
        "class": "knowledge",
        "grade": {"type": "regex", "patterns": ["fts_primary", "(?i)rrf"]},
        "prompt": "q",
    }
    result = grade_task(
        task,
        final_text="We force fts_primary because equal RRF collapsed recall.",
        worktree=Path("."),
    )
    assert result.passed


def test_seed_endtask_brain(tmp_path: Path) -> None:
    fixture = load_endtask_fixture()
    # Tiny project dir (not a full git worktree)
    info = seed_endtask_brain(tmp_path, fixture, run_graph_sync=False)
    assert info["neurons"] >= 25
    assert (tmp_path / ".brain" / "brain.db").is_file()


def test_build_groq_user_prompt() -> None:
    with_pack = build_groq_user_prompt("Why 1500?", pack_text="budget is 1500")
    assert "PROJECT MEMORY PACK" in with_pack
    assert "budget is 1500" in with_pack
    bare = build_groq_user_prompt("Why 1500?", pack_text=None)
    assert "NO project memory pack" in bare


def test_scorecard_render_and_ndjson(tmp_path: Path) -> None:
    records = [
        EndTaskRunRecord(
            task_id="k_budget_cap",
            task_class="knowledge",
            arm="with_brainkm",
            repeat=1,
            passed=True,
            grade_detail="all_patterns",
            grade_method="regex",
            context_tokens=1200,
            input_tokens=1200,
            output_tokens=80,
            tokens_proxy=100,
            wall_ms=1500,
            tool_calls=2,
            status="finished",
        ),
        EndTaskRunRecord(
            task_id="k_budget_cap",
            task_class="knowledge",
            arm="without",
            repeat=1,
            passed=False,
            grade_detail="missing",
            grade_method="regex",
            context_tokens=1800,
            input_tokens=1800,
            output_tokens=90,
            tokens_proxy=120,
            wall_ms=2000,
            tool_calls=0,
            status="finished",
        ),
    ]
    report = EndTaskReport(records=records, model="composer-2.5", dry_run=False)
    md = render_endtask_markdown(report)
    assert "with brainkm" in md
    assert "1200" in md
    out = tmp_path / "runs.ndjson"
    write_ndjson(out, records)
    assert out.read_text(encoding="utf-8").count("\n") == 2
