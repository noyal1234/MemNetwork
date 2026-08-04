"""Tests for Antigravity CLI endtask tool-hop counting and argv order."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "antigravity_endtask_harness.py"


def _load():
    name = "antigravity_endtask_harness"
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_count_tool_hops_ignores_path_false_positives(tmp_path: Path) -> None:
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


def test_print_argv_order() -> None:
    text = _SCRIPT.read_text(encoding="utf-8")
    assert 'cmd.extend(["--print", prompt])' in text
    assert 'cmd = [agy_bin, "--print", f"--print-timeout=' not in text
    assert 'cmd.append(f"--model={model}")' in text


def test_tier_default_is_core() -> None:
    text = _SCRIPT.read_text(encoding="utf-8")
    assert 'default="core"' in text
    assert "select_tasks_for_tier" in text


def test_quota_error_detection() -> None:
    bench = _load()
    assert bench._is_quota_error(
        "error:exit_1:Error: Individual quota reached. Please upgrade"
    )
    assert not bench._is_quota_error("error:exit_1:timeout waiting")

def test_load_finished_records_skips_errors(tmp_path: Path) -> None:
    bench = _load()
    nd = tmp_path / "partial.ndjson"
    rows = [
        {"_manifest": {"model": "x"}},
        {
            "task_id": "k_budget_cap",
            "task_class": "knowledge",
            "arm": "with_brainkm",
            "repeat": 1,
            "passed": True,
            "grade_detail": "ok",
            "grade_method": "regex",
            "context_tokens": None,
            "input_tokens": None,
            "output_tokens": None,
            "tokens_proxy": 1,
            "wall_ms": 1.0,
            "tool_calls": 1,
            "status": "finished",
            "mcp_ok": True,
        },
        {
            "task_id": "k_layers",
            "task_class": "knowledge",
            "arm": "without",
            "repeat": 1,
            "passed": False,
            "grade_detail": "quota",
            "grade_method": "regex",
            "context_tokens": None,
            "input_tokens": None,
            "output_tokens": None,
            "tokens_proxy": 0,
            "wall_ms": 1.0,
            "tool_calls": 0,
            "status": "error:exit_1:quota",
            "mcp_ok": True,
        },
    ]
    nd.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    loaded = bench.load_finished_records_from_ndjson(nd)
    assert len(loaded) == 1
    assert loaded[0].task_id == "k_budget_cap"
