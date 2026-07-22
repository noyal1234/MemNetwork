"""Tests for endtask_protocol (manifest, MCP_db, Core tier, nullable tokens)."""

from __future__ import annotations

from pathlib import Path

from brainkm.services.endtask_bench import EndTaskReport, EndTaskRunRecord, load_endtask_fixture
from brainkm.services.endtask_protocol import (
    PROTOCOL_VERSION,
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
    assert "Mean prompt tokens" in md
