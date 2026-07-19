"""Antigravity client: MCP serverUrl, hooks schema, stdout envelopes, install."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from brainkm.models.brain_config import BrainConfig, CaptureConfig
from brainkm.services.client_adapters import get_client_adapter
from brainkm.services.connect import mcp_config_path_for_client, run_connect
from brainkm.services.hooks import (
    HookRunResult,
    build_antigravity_hook_stdout,
    normalize_antigravity_stdin,
)
from brainkm.services.install import (
    build_antigravity_hooks_config,
    merge_antigravity_hooks_json,
    run_install,
)
from brainkm.services.mcp_transport import build_mcp_config, http_url_field_for_client


def test_antigravity_adapter_kind() -> None:
    adapter = get_client_adapter("antigravity")
    assert adapter.kind == "antigravity"
    assert adapter.config_dir_name() == ".agents"
    assert adapter.transcript_style() == "antigravity_jsonl"
    assert "preInvocation" in adapter.hook_events()


def test_http_url_field_antigravity() -> None:
    assert http_url_field_for_client("antigravity") == "serverUrl"
    assert http_url_field_for_client("cursor") == "url"


def test_mcp_config_antigravity_http_uses_server_url() -> None:
    payload = build_mcp_config(transport="http", host="127.0.0.1", port=8765, client="antigravity")
    entry = payload["mcpServers"]["brainkm"]
    assert "serverUrl" in entry
    assert "url" not in entry
    assert entry["serverUrl"] == "http://127.0.0.1:8765/mcp"


def test_mcp_config_path() -> None:
    root = Path("/tmp/proj")
    assert mcp_config_path_for_client(root, "antigravity") == root / ".agents" / "mcp_config.json"


def test_normalize_antigravity_stdin_tool_call() -> None:
    raw = {
        "conversationId": "conv-1",
        "transcriptPath": "/tmp/t.jsonl",
        "toolCall": {
            "name": "write_to_file",
            "args": {"TargetFile": "foo.py", "CodeContent": "x"},
        },
    }
    out = normalize_antigravity_stdin(raw, event="PreToolUse")
    assert out["session_id"] == "conv-1"
    assert out["tool_name"] == "write_to_file"
    assert out["tool_input"]["path"] == "foo.py"


def test_antigravity_stdout_envelopes() -> None:
    inject = HookRunResult(
        hook="PreInvocation",
        session_id="s",
        skipped=False,
        reason=None,
        additional_context="pack here",
    )
    assert build_antigravity_hook_stdout(inject, "PreInvocation") == {
        "injectSteps": [{"ephemeralMessage": "pack here"}]
    }
    empty = HookRunResult(hook="PreInvocation", session_id="s", skipped=True, reason="x")
    assert build_antigravity_hook_stdout(empty, "PreInvocation") == {}
    assert build_antigravity_hook_stdout(empty, "PreToolUse") == {"decision": "allow"}
    assert build_antigravity_hook_stdout(empty, "Stop") == {"decision": "stop"}


def test_merge_antigravity_hooks_preserves_foreign() -> None:
    existing = {
        "other": {"PreInvocation": [{"type": "command", "command": "echo hi"}]},
    }
    incoming = build_antigravity_hooks_config("/bin/brainkm")
    merged = merge_antigravity_hooks_json(existing, incoming)
    assert "other" in merged
    assert "brainkm" in merged
    blob = json.dumps(merged["brainkm"])
    assert "--client antigravity" in blob
    assert "PreInvocation" in merged["brainkm"]


def test_install_antigravity(tmp_path: Path) -> None:
    result = run_install(
        project_dir=tmp_path,
        dev=True,
        force=True,
        no_graph=True,
        client="antigravity",
    )
    assert (tmp_path / ".agents" / "mcp_config.json").is_file()
    assert (tmp_path / ".agents" / "hooks.json").is_file()
    assert (tmp_path / ".agents" / "rules" / "brainkm.md").is_file()
    assert (tmp_path / ".agents" / "skills" / "brainkm-routing" / "SKILL.md").is_file()
    assert not (tmp_path / ".cursor").exists()
    mcp = json.loads((tmp_path / ".agents" / "mcp_config.json").read_text())
    assert "brainkm" in mcp["mcpServers"]
    hooks = json.loads((tmp_path / ".agents" / "hooks.json").read_text())
    assert "--client antigravity" in json.dumps(hooks)
    assert "SessionStart" in hooks["brainkm"]
    cfg = BrainConfig.model_validate(
        json.loads((tmp_path / ".brain" / "config.json").read_text())
    )
    assert cfg.capture.auto_observe is True
    assert cfg.capture.distill_mode in ("antigravity", "rules")
    assert result.project_dir == tmp_path


def test_doctor_warns_on_url_instead_of_server_url(tmp_path: Path) -> None:
    from brainkm.services.mcp_doctor import inspect_antigravity_wiring

    agents = tmp_path / ".agents"
    agents.mkdir()
    (agents / "mcp_config.json").write_text(
        json.dumps(
            {"mcpServers": {"brainkm": {"url": "http://127.0.0.1:8765/mcp"}}}
        ),
        encoding="utf-8",
    )
    (agents / "hooks.json").write_text(
        json.dumps(
            {
                "brainkm": {
                    "PreInvocation": [
                        {
                            "type": "command",
                            "command": "brainkm pre-invocation --client antigravity",
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    notes = inspect_antigravity_wiring(tmp_path)
    assert any("serverUrl" in n for n in notes)


def test_connect_antigravity_http(tmp_path: Path) -> None:
    run_install(
        project_dir=tmp_path,
        dev=True,
        force=True,
        no_graph=True,
        client="antigravity",
    )
    result = run_connect(
        "antigravity",
        tmp_path,
        transport="http",
        hooks=True,
        dev=True,
    )
    mcp = json.loads((tmp_path / ".agents" / "mcp_config.json").read_text())
    entry = mcp["mcpServers"]["brainkm"]
    assert entry.get("serverUrl") == "http://127.0.0.1:8765/mcp"
    assert "command" not in entry
    assert result.mcp_url is not None


def test_legacy_mcp_distill_coerces_to_claude() -> None:
    cfg = BrainConfig(capture=CaptureConfig(distill_mode="mcp"))  # type: ignore[arg-type]
    assert cfg.capture.distill_mode == "claude"


def test_get_distill_adapter_claude_and_antigravity() -> None:
    from brainkm.adapters.distill import get_distill_adapter

    claude = get_distill_adapter(BrainConfig(capture=CaptureConfig(distill_mode="claude")))
    assert claude.mode == "claude"
    agy = get_distill_adapter(
        BrainConfig(capture=CaptureConfig(distill_mode="antigravity"))
    )
    assert agy.mode == "antigravity"


def test_antigravity_transcript_fixture() -> None:
    from brainkm.adapters.transcript_v1 import ANTIGRAVITY_JSONL, parse_transcript_file

    fixture = Path(__file__).parent / "fixtures" / "antigravity_transcript.jsonl"
    parsed = parse_transcript_file(fixture, session_id="agy-fixture")
    assert parsed.format_name == ANTIGRAVITY_JSONL
    roles = [m.role for m in parsed.messages]
    assert "user" in roles and "assistant" in roles
    user_texts = [m.text for m in parsed.messages if m.role == "user"]
    assert any("Add antigravity hooks" in t for t in user_texts)
    assert not any("<USER_REQUEST>" in t for t in user_texts)
    assert len(parsed.rounds) >= 1


def test_agy_session_inject_and_stop_gates() -> None:
    from brainkm.services.antigravity_session import (
        AgySessionState,
        should_inject_pack,
        should_run_distill,
        should_synthetic_handover,
    )

    state = AgySessionState(conversation_id="c1")
    assert should_inject_pack(state, invocation_num=0, pack_hash="a")
    state.bootstrap_done = True
    state.last_inject_invocation = 0
    state.last_inject_pack_hash = "a"
    assert not should_inject_pack(state, invocation_num=3, pack_hash="a")
    assert should_inject_pack(state, invocation_num=8, pack_hash="a")
    assert should_inject_pack(state, invocation_num=3, pack_hash="b")

    assert not should_run_distill(state, fully_idle=False)
    assert should_run_distill(state, fully_idle=True)
    state.last_distill_at = 1e18
    assert not should_run_distill(state, fully_idle=True)
    assert should_run_distill(state, fully_idle=True, force=True)

    assert should_synthetic_handover(state, transcript_bytes=300_000, steps=0)
    assert should_synthetic_handover(
        AgySessionState(conversation_id="c2"), transcript_bytes=0, steps=40
    )
