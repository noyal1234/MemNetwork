"""Tests for Antigravity CLI endtask tool-hop counting and MCP_db integrity."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "antigravity_endtask_harness.py"
)


def _load():
    name = "antigravity_endtask_harness"
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_count_tool_hops_ignores_path_false_positives(tmp_path: Path) -> None:
    """VIEW_FILE of brainkm/ paths must not inflate MCP metrics."""
    bench = _load()
    lines = [
        {
            "type": "USER_INPUT",
            "content": "<USER_REQUEST>\nTASK: open antigravity distill\n</USER_REQUEST>",
        },
        {"type": "GREP_SEARCH", "content": "pattern"},
        {
            "type": "VIEW_FILE",
            "content": "file path: brainkm/brainkm/services/hooks.py with recall",
        },
        {
            "type": "PLANNER_RESPONSE",
            "content": "Uses agy print and RulesDistillAdapter; Groq when key set.",
        },
    ]
    path = tmp_path / "transcript_full.jsonl"
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    tools, types, turns, final, user = bench.count_tool_hops(path)
    assert tools == 2
    assert types["GREP_SEARCH"] == 1
    assert turns == 1
    assert "task" in user.lower()
    assert "agy" in final.lower()


def test_count_mcp_activity_from_session_activity(tmp_path: Path) -> None:
    bench = _load()
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
            ("s", "x", None, "context_pack:3", "mcp", "2026-07-22T12:00:01+00:00"),
            ("s", "x", None, "Write", "hook", "2026-07-22T12:00:02+00:00"),
            ("s", "x", None, "brain_stats", "mcp", "2026-07-22T11:00:00+00:00"),
        ],
    )
    con.commit()
    con.close()
    total, tools = bench.count_mcp_activity(
        db, since_iso="2026-07-22T11:59:00+00:00"
    )
    assert total == 2
    assert tools.get("recall") == 1
    assert tools.get("context_pack") == 1
    assert "brain_stats" not in tools


def test_grade_scenario_groups() -> None:
    bench = _load()
    scenario = {
        "must_include_any": [
            ["agy", "print"],
            ["rules", "RulesDistill"],
            ["groq"],
        ],
        "min_groups": 2,
    }
    ok, detail = bench.grade_scenario(
        "We shell to agy --print; RulesDistillAdapter is the fallback.", scenario
    )
    assert ok
    assert "groups=2/2" in detail or "groups=2/" in detail

    bad, detail2 = bench.grade_scenario(
        "Please clarify --print-timeout=5m flag usage.", scenario
    )
    assert not bad
    assert "prompt_misrouted" in detail2


def test_print_argv_order() -> None:
    """Regression: --print must not precede the timeout flag as its prompt arg."""
    text = _SCRIPT.read_text(encoding="utf-8")
    assert 'cmd.extend(["--print", prompt])' in text
    assert 'cmd = [agy_bin, "--print", f"--print-timeout=' not in text


def test_stdio_mcp_config_points_at_repo(tmp_path: Path) -> None:
    bench = _load()
    repo = tmp_path / "repo"
    (repo / ".venv" / "bin").mkdir(parents=True)
    brainkm_bin = repo / ".venv" / "bin" / "brainkm"
    brainkm_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    cfg = bench.build_stdio_mcp_config(repo)
    entry = cfg["mcpServers"]["brainkm"]
    assert entry["command"] == str(brainkm_bin)
    assert "--project-dir" in entry["args"]
    assert str(repo) in entry["args"]


def test_render_marks_invalid_when_no_mcp() -> None:
    bench = _load()
    rec = bench.AgyEndtaskRecord(
        scenario_id="agy_arch_pivot",
        arm="with_brainkm",
        repeat=1,
        passed=True,
        grade_detail="groups=2/2",
        tool_calls=10,
        tool_types={},
        turns=3,
        mcp_calls=0,
        mcp_tools={},
        mcp_ok=False,
        prompt_tokens_est=10,
        completion_tokens_est=20,
        wall_ms=1000,
        status="finished",
        transcript_path=None,
        final_text_preview="ok",
        user_prompt_ok=True,
    )
    md = bench.render_markdown(
        bench.AgyEndtaskReport(records=[rec], agy_bin="/bin/agy", notes=[])
    )
    assert "INVALID for MCP A/B" in md
    assert "MCP_db" in md
