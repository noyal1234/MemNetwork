"""Codex CLI first-class client: install, hooks, MCP TOML, stdout, distill."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

import tomllib
from typer.testing import CliRunner

from brainkm.adapters.transcript_v1 import (
    CODEX_JSONL,
    detect_transcript_format,
    parse_codex_jsonl_lines,
    parse_transcript_file,
)
from brainkm.cli import app
from brainkm.db.migrate import migrate
from brainkm.services.connect import mcp_config_path_for_client, run_connect
from brainkm.services.hooks import HookRunResult, build_codex_hook_stdout, run_session_end
from brainkm.services.install import (
    build_codex_hooks_config,
    merge_codex_hooks_json,
    run_install,
)
from brainkm.services.mcp_doctor import build_mcp_doctor_report, inspect_codex_wiring
from brainkm.services.mcp_transport import (
    mcp_entry_has_bearer_header,
    read_codex_mcp_server_entry,
    write_codex_mcp_config,
)


def test_codex_hooks_template_matches_builder() -> None:
    template = json.loads(
        resources.files("brainkm.hooks.codex").joinpath("hooks.json").read_text(encoding="utf-8")
    )
    built = build_codex_hooks_config("brainkm")
    assert template == built


def test_build_codex_hooks_config_schema() -> None:
    hooks = build_codex_hooks_config("/usr/local/bin/brainkm")
    events = hooks["hooks"]
    assert "SessionStart" in events
    assert "Stop" in events
    assert "SessionEnd" not in events
    assert "UserPromptSubmit" in events
    assert "PreCompact" in events
    assert "PostCompact" in events

    start = events["SessionStart"][0]
    assert start["matcher"] == "startup|resume|clear"
    cmd = start["hooks"][0]["command"]
    assert "--client codex" in cmd
    assert "session-start" in cmd

    stop_cmd = events["Stop"][0]["hooks"][0]["command"]
    assert "session-end" in stop_cmd
    assert "--client codex" in stop_cmd

    pre = events["PreToolUse"][0]
    assert "Bash" in pre["matcher"]
    assert "apply_patch" in pre["matcher"]
    assert "mcp__.*" in pre["matcher"]


def test_merge_codex_hooks_preserves_foreign() -> None:
    existing = {
        "description": "user hooks",
        "hooks": {
            "SessionStart": [
                {
                    "hooks": [
                        {"type": "command", "command": "echo foreign"},
                    ]
                },
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "/old/brainkm session-start --stdin --client codex",
                        }
                    ]
                },
            ]
        },
    }
    incoming = build_codex_hooks_config("/new/brainkm")
    merged = merge_codex_hooks_json(existing, incoming)
    assert merged["description"] == "user hooks"
    groups = merged["hooks"]["SessionStart"]
    commands = [
        handler["command"]
        for group in groups
        for handler in group["hooks"]
    ]
    assert "echo foreign" in commands
    assert any(c.startswith("/new/brainkm ") for c in commands)
    assert not any("/old/brainkm" in c for c in commands)


def test_build_codex_hook_stdout_session_start() -> None:
    result = HookRunResult(
        hook="SessionStart",
        session_id="s1",
        skipped=False,
        reason=None,
        additional_context="## brain pack",
    )
    out = build_codex_hook_stdout(result, "sessionStart")
    specific = out["hookSpecificOutput"]
    assert specific["hookEventName"] == "SessionStart"
    assert specific["additionalContext"] == "## brain pack"
    assert out["continue"] is True


def test_build_codex_hook_stdout_stop_is_json_continue() -> None:
    result = HookRunResult(
        hook="SessionEnd",
        session_id="s1",
        skipped=False,
        reason=None,
    )
    out = build_codex_hook_stdout(result, "sessionEnd")
    assert out == {"continue": True}
    assert "decision" not in out


def test_build_codex_hook_stdout_pre_tool_with_context() -> None:
    result = HookRunResult(
        hook="PreToolUse",
        session_id="s1",
        skipped=False,
        reason=None,
        additional_context="pack",
    )
    out = build_codex_hook_stdout(result, "preToolUse")
    specific = out["hookSpecificOutput"]
    assert specific["hookEventName"] == "PreToolUse"
    assert specific["additionalContext"] == "pack"


def test_run_install_codex_writes_toml_hooks_skill(tmp_path: Path) -> None:
    result = run_install(tmp_path, dev=True, force=True, client="codex", no_graph=True)
    config = tmp_path / ".codex" / "config.toml"
    hooks = tmp_path / ".codex" / "hooks.json"
    skill = tmp_path / ".codex" / "skills" / "brainkm-routing" / "SKILL.md"
    rule = tmp_path / ".codex" / "rules" / "brainkm.md"
    agents = tmp_path / "AGENTS.md"

    assert config.is_file()
    assert hooks.is_file()
    assert skill.is_file()
    assert rule.is_file()
    assert agents.is_file()
    assert not (tmp_path / ".codex" / "mcp.json").exists()

    data = tomllib.loads(config.read_text(encoding="utf-8"))
    entry = data["mcp_servers"]["brainkm"]
    assert "command" in entry
    assert "args" in entry
    assert "url" not in entry

    hooks_data = json.loads(hooks.read_text(encoding="utf-8"))
    assert "SessionStart" in hooks_data["hooks"]
    assert "Stop" in hooks_data["hooks"]
    assert "session-end" in hooks_data["hooks"]["Stop"][0]["hooks"][0]["command"]
    assert any("trust" in w.lower() or "/hooks" in w for w in result.warnings)
    assert "OpenAI Codex" in agents.read_text(encoding="utf-8")


def test_run_install_codex_sets_distill_mode_when_cli_present(
    tmp_path: Path, monkeypatch
) -> None:
    from brainkm.services.config_loader import load_brain_config
    from brainkm.services import install as install_mod

    monkeypatch.setattr(install_mod, "_cli_on_path", lambda name: name == "codex")
    run_install(tmp_path, dev=True, force=True, client="codex", no_graph=True)
    cfg = load_brain_config(tmp_path)
    assert cfg.capture.distill_mode == "codex"
    assert cfg.capture.auto_observe is True


def test_codex_toml_merge_preserves_user_keys(tmp_path: Path) -> None:
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(
        'model = "gpt-5"\n\n[features]\nhooks = true\n\n'
        '[mcp_servers.other]\ncommand = "echo"\n',
        encoding="utf-8",
    )
    write_codex_mcp_config(config, dev=True, transport="stdio")
    data = tomllib.loads(config.read_text(encoding="utf-8"))
    assert data["model"] == "gpt-5"
    assert data["features"]["hooks"] is True
    assert data["mcp_servers"]["other"]["command"] == "echo"
    assert "command" in data["mcp_servers"]["brainkm"]


def test_connect_codex_http_writes_url_and_bearer(tmp_path: Path) -> None:
    migrate(project_dir=tmp_path, run_integrity_check=False)
    result = run_connect("codex", tmp_path, transport="http", hooks=True, dev=True)
    config = tmp_path / ".codex" / "config.toml"
    assert config in result.files_written
    assert mcp_config_path_for_client(tmp_path, "codex") == config

    entry = read_codex_mcp_server_entry(config)
    assert entry is not None
    assert "url" in entry
    assert mcp_entry_has_bearer_header(entry)
    assert "http_headers" in entry
    assert "command" not in entry

    hooks = json.loads((tmp_path / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    assert "--client codex" in hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]


def test_session_end_skips_when_stop_hook_active(tmp_path: Path) -> None:
    migrate(project_dir=tmp_path, run_integrity_check=False)
    raw = json.dumps(
        {
            "session_id": "s-codex",
            "transcript_path": str(tmp_path / "missing.jsonl"),
            "stop_hook_active": True,
        }
    )
    result = run_session_end(raw, project_dir=tmp_path)
    assert result.skipped
    assert result.reason == "stop_hook_active"


def test_codex_fail_soft_emits_continue_json(tmp_path: Path) -> None:
    runner = CliRunner()
    # Invalid JSON → handler error → fail-soft exit 0 with continue JSON
    result = runner.invoke(
        app,
        ["session-end", "--stdin", "--client", "codex", "--project-dir", str(tmp_path)],
        input="not-json",
    )
    assert result.exit_code == 0
    out = json.loads(result.stdout.strip() or "{}")
    assert out.get("continue") is True


def test_codex_transcript_detect_and_parse(tmp_path: Path) -> None:
    lines = [
        json.dumps({"type": "session_meta", "payload": {"id": "abc"}}),
        json.dumps(
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Use brainkm for memory"}],
                },
            }
        ),
        json.dumps(
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Will pin decisions via remember only.",
                        }
                    ],
                },
            }
        ),
        json.dumps(
            {
                "type": "event_msg",
                "payload": {"type": "agent_message", "message": "ignored nested"},
            }
        ),
    ]
    assert detect_transcript_format(lines) == CODEX_JSONL
    parsed = parse_codex_jsonl_lines(lines, session_id="codex-1")
    assert parsed.format_name == CODEX_JSONL
    roles = [m.role for m in parsed.messages]
    assert "user" in roles
    assert "assistant" in roles
    assert any("brainkm" in m.text for m in parsed.messages)

    path = tmp_path / "rollout.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    from_file = parse_transcript_file(path, session_id="codex-1")
    assert from_file.format_name == CODEX_JSONL
    assert len(from_file.messages) >= 2


def test_doctor_inspects_codex_wiring(tmp_path: Path) -> None:
    migrate(project_dir=tmp_path, run_integrity_check=False)
    run_install(tmp_path, dev=True, force=True, client="codex", no_graph=True)
    notes = inspect_codex_wiring(tmp_path)
    assert any("trust" in n.lower() or "/hooks" in n for n in notes)

    report = build_mcp_doctor_report(tmp_path)
    codex = next(c for c in report.clients if c.client == "codex")
    assert codex.present
    assert codex.hooks_present
    assert codex.transport == "stdio"
