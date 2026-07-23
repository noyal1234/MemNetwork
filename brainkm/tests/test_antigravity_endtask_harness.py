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


def test_tier_default_is_core() -> None:
    text = _SCRIPT.read_text(encoding="utf-8")
    assert 'default="core"' in text
    assert "select_tasks_for_tier" in text
