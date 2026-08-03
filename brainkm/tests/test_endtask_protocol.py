"""Tests for endtask_protocol (manifest, MCP_db, Core tier, nullable tokens)."""

from __future__ import annotations

from pathlib import Path

from brainkm.services.endtask_bench import EndTaskReport, EndTaskRunRecord, load_endtask_fixture
from brainkm.services.endtask_protocol import (
    H2H_PUBLISH_SET,
    PROTOCOL_VERSION,
    WITH_ARM_MCP_PREFIX,
    RunManifest,
    core_task_ids,
    count_mcp_activity,
    mcp_ok_for_arm,
    render_protocol_markdown,
    select_tasks_for_tier,
)


def test_core_tier_six_mixed_tasks() -> None:
    fixture = load_endtask_fixture()
    ids = core_task_ids(fixture)
    assert len(ids) == 6
    assert "core_task_ids" in fixture
    tasks = select_tasks_for_tier(fixture, tier="core")
    assert len(tasks) == 6
    classes = {t["class"] for t in tasks}
    assert "knowledge" in classes
    assert "change" in classes
    full = select_tasks_for_tier(fixture, tier="full")
    assert len(full) == 20


def test_count_mcp_activity(tmp_path: Path) -> None:
    import sqlite3

    db = tmp_path / "brain.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE session_activity ("
        "id INTEGER PRIMARY KEY, session_id TEXT, kind TEXT, node_id TEXT, "
        "tool_name TEXT, source TEXT, created_at TEXT)"
    )
    con.executemany(
        "INSERT INTO session_activity "
        "(session_id, kind, node_id, tool_name, source, created_at) VALUES (?,?,?,?,?,?)",
        [
            ("s", "x", None, "recall:5", "mcp", "2026-07-22T12:00:00+00:00"),
            ("s", "x", None, "Write", "hook", "2026-07-22T12:00:01+00:00"),
        ],
    )
    con.commit()
    con.close()
    total, tools = count_mcp_activity(db, since_iso="2026-07-22T11:59:00+00:00")
    assert total == 1
    assert tools.get("recall") == 1
    assert mcp_ok_for_arm(arm="with_brainkm", mcp_calls=1)
    assert not mcp_ok_for_arm(arm="with_brainkm", mcp_calls=0)
    assert mcp_ok_for_arm(arm="without", mcp_calls=0)


def test_render_tokens_na_when_unsupported() -> None:
    rec = EndTaskRunRecord(
        task_id="k_budget_cap",
        task_class="knowledge",
        arm="with_brainkm",
        repeat=1,
        passed=True,
        grade_detail="all_patterns",
        grade_method="regex",
        context_tokens=None,
        input_tokens=None,
        output_tokens=None,
        tokens_proxy=100,
        wall_ms=1000,
        tool_calls=5,
        status="finished",
        mcp_calls=1,
        mcp_ok=True,
        tokens_source="unavailable",
    )
    manifest = RunManifest(
        protocol_version=PROTOCOL_VERSION,
        tier="core",
        host="antigravity",
        tokens_supported=False,
        run_id="2026-07-22-antigravity-core-abc",
    )
    md = render_protocol_markdown(
        EndTaskReport(records=[rec], fixture_id="endtask_v1"),
        manifest=manifest,
    )
    assert "N/A" in md
    assert PROTOCOL_VERSION in md
    assert "Cumulative prompt tokens" in md
    assert "Tokens / round" in md


def test_with_arm_mcp_prefix_shared() -> None:
    assert PROTOCOL_VERSION == "endtask_protocol/1.2"
    assert H2H_PUBLISH_SET == "endtask_h2h/2"
    assert "brainkm MCP" in WITH_ARM_MCP_PREFIX
    assert "context_pack" in WITH_ARM_MCP_PREFIX
    assert WITH_ARM_MCP_PREFIX.endswith("\n\n")


def test_cursor_harness_applies_with_arm_routing() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "endtask_harness.py"
    text = script.read_text(encoding="utf-8")
    assert "WITH_ARM_MCP_PREFIX" in text
    assert 'setting_sources = ["project"]' in text
    assert "WITH_ARM_MCP_PREFIX + base_prompt" in text


def test_tokens_per_round_normalizes_cumulative_billing() -> None:
    """A high-tool arm must not look context-heavy when its per-round context is smaller.

    Hosts bill input_tokens cumulatively across round-trips, so cumulative alone
    conflates round count with context size — the defect that made the 2026-08-02
    Codex card read as "brainkm costs 2.1x context".
    """
    from brainkm.services.endtask_protocol import (
        resolve_model_rounds,
        resolve_tokens_per_round,
    )

    def _rec(arm: str, tools: int, prompt: int) -> EndTaskRunRecord:
        return EndTaskRunRecord(
            task_id="t",
            task_class="knowledge",
            arm=arm,  # type: ignore[arg-type]
            repeat=1,
            passed=True,
            grade_detail="",
            grade_method="regex",
            context_tokens=prompt,
            input_tokens=prompt,
            output_tokens=10,
            tokens_proxy=None,
            wall_ms=1.0,
            tool_calls=tools,
            status="finished",
            prompt_tokens=prompt,
            tokens_source="host_usage",
        )

    # with-arm: 4 rounds x 10k. without-arm: 2 rounds x 15k.
    # Cumulative says with-arm is 1.33x worse; per-round says it is 33% better.
    with_rec = _rec("with_brainkm", tools=3, prompt=40_000)
    without_rec = _rec("without", tools=1, prompt=30_000)

    assert resolve_model_rounds(with_rec) == 4
    assert resolve_model_rounds(without_rec) == 2
    assert resolve_tokens_per_round(with_rec) == 10_000
    assert resolve_tokens_per_round(without_rec) == 15_000

    # An explicit model_rounds overrides the tool_calls + 1 derivation.
    with_rec.model_rounds = 5
    assert resolve_model_rounds(with_rec) == 5
    assert resolve_tokens_per_round(with_rec) == 8_000
