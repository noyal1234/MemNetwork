"""Tests for Codex CLI endtask JSONL parsing and defaults."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "codex_endtask_harness.py"


def _load():
    name = "codex_endtask_harness"
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_default_model_is_luna_low_effort() -> None:
    text = _SCRIPT.read_text(encoding="utf-8")
    assert 'DEFAULT_MODEL = "gpt-5.6-luna"' in text
    assert 'DEFAULT_REASONING_EFFORT = "low"' in text
    assert 'default="core"' in text
    assert "select_tasks_for_tier" in text
    assert "WITH_ARM_MCP_PREFIX" in text


def test_parse_codex_exec_jsonl_usage_and_tools() -> None:
    bench = _load()
    lines = [
        {"type": "thread.started", "thread_id": "t1"},
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {
                "id": "i1",
                "type": "mcp_tool_call",
                "server": "brainkm",
                "tool": "context_pack",
                "status": "completed",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "i2",
                "type": "command_execution",
                "command": "bash -lc ls",
                "status": "completed",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "i3",
                "type": "agent_message",
                "text": "Budget cap is 1500 tokens.",
            },
        },
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 24763,
                "cached_input_tokens": 24448,
                "output_tokens": 122,
                "reasoning_output_tokens": 0,
            },
        },
    ]
    stdout = "\n".join(json.dumps(x) for x in lines) + "\n"
    parsed = bench.parse_codex_exec_jsonl(stdout)
    assert parsed["final_text"] == "Budget cap is 1500 tokens."
    assert parsed["tool_calls"] == 2
    assert parsed["prompt_tokens"] == 24763  # do not double-count cached
    assert parsed["completion_tokens"] == 122
    assert parsed["turn_failed"] is False


def test_parse_codex_exec_jsonl_turn_failed() -> None:
    bench = _load()
    stdout = json.dumps({"type": "turn.failed", "error": "quota exceeded"}) + "\n"
    parsed = bench.parse_codex_exec_jsonl(stdout)
    assert parsed["turn_failed"] is True
    assert "quota" in parsed["error_msg"]


def test_write_isolated_codex_home_with_and_without_mcp(tmp_path: Path) -> None:
    bench = _load()
    with_home = bench.write_isolated_codex_home(
        worktree=tmp_path,
        model="gpt-5.6-luna",
        reasoning_effort="low",
        with_brainkm=True,
    )
    try:
        text = (with_home / "config.toml").read_text(encoding="utf-8")
        assert "[mcp_servers.brainkm]" in text
        assert "--project-dir" in text
        assert 'model = "gpt-5.6-luna"' in text
    finally:
        bench.remove_codex_home(with_home)

    without_home = bench.write_isolated_codex_home(
        worktree=tmp_path,
        model="gpt-5.6-luna",
        reasoning_effort="low",
        with_brainkm=False,
    )
    try:
        text = (without_home / "config.toml").read_text(encoding="utf-8")
        assert "[mcp_servers.brainkm]" not in text
    finally:
        bench.remove_codex_home(without_home)


def test_neutralize_agents_md(tmp_path: Path) -> None:
    bench = _load()
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# brainkm routing\ncall context_pack\n", encoding="utf-8")
    bench.neutralize_agents_md(tmp_path)
    text = agents.read_text(encoding="utf-8")
    assert "Endtask harness isolation" in text
    assert "context_pack" not in text


def test_has_codex_auth_respects_api_key(monkeypatch) -> None:
    bench = _load()
    monkeypatch.setenv("CODEX_API_KEY", "sk-test")
    assert bench.has_codex_auth() is True
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
