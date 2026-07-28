"""Claude Code silent-memory install, hooks stdout, and lifecycle tests."""

from __future__ import annotations

import json
from pathlib import Path

from brainkm.models.brain_config import BrainConfig
from brainkm.services.config_loader import load_brain_config
from brainkm.services.connect import hooks_path_for_client, run_connect
from brainkm.services.hooks import (
    HookRunResult,
    build_claude_hook_stdout,
    build_cursor_hook_stdout,
    run_agent_stop,
    run_subagent_stop,
)
from brainkm.services.install import (
    build_claude_hooks_config,
    merge_claude_settings_hooks,
    run_install,
)
from brainkm.services.mcp_doctor import inspect_claude_wiring


def test_build_claude_hooks_config_schema() -> None:
    hooks = build_claude_hooks_config("/usr/local/bin/brainkm")
    events = hooks["hooks"]
    assert "SessionStart" in events
    assert "PostCompact" in events
    assert "SubagentStart" in events
    assert "SubagentStop" in events
    assert "Stop" in events
    assert "sessionStart" not in events

    start = events["SessionStart"][0]
    assert "hooks" in start
    cmd = start["hooks"][0]["command"]
    assert cmd.startswith("/usr/local/bin/brainkm ")
    assert "--client claude" in cmd
    assert start["hooks"][0]["type"] == "command"

    post = events["PostCompact"][0]["hooks"][0]["command"]
    assert "post-compact --stdin" in post
    assert "--client claude" in post

    pre = events["PreToolUse"][0]
    assert "Bash" in pre["matcher"] or "Write" in pre["matcher"]


def test_merge_claude_settings_hooks_preserves_foreign() -> None:
    existing = {
        "autoMemoryEnabled": True,
        "permissions": {"allow": ["Bash"]},
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
                            "command": "/old/brainkm session-start --stdin --client claude",
                        }
                    ]
                },
            ]
        },
    }
    incoming = build_claude_hooks_config("/new/brainkm")
    merged = merge_claude_settings_hooks(existing, incoming)

    assert merged["autoMemoryEnabled"] is True
    assert merged["permissions"]["allow"] == ["Bash"]
    groups = merged["hooks"]["SessionStart"]
    commands = []
    for group in groups:
        for handler in group["hooks"]:
            commands.append(handler["command"])
    assert "echo foreign" in commands
    assert any(c.startswith("/new/brainkm ") for c in commands)
    assert not any("/old/brainkm" in c for c in commands)


def test_build_claude_hook_stdout_session_start() -> None:
    result = HookRunResult(
        hook="SessionStart",
        session_id="s1",
        skipped=False,
        reason=None,
        additional_context="## brain pack",
    )
    out = build_claude_hook_stdout(result, "sessionStart")
    assert out is not None
    specific = out["hookSpecificOutput"]
    assert specific["hookEventName"] == "SessionStart"
    assert specific["additionalContext"] == "## brain pack"
    assert "additional_context" not in out


def test_build_claude_hook_stdout_pre_tool() -> None:
    result = HookRunResult(
        hook="PreToolUse",
        session_id="s1",
        skipped=False,
        reason=None,
        additional_context="pack",
    )
    out = build_claude_hook_stdout(result, "preToolUse")
    assert out is not None
    specific = out["hookSpecificOutput"]
    assert specific["permissionDecision"] == "allow"
    assert specific["additionalContext"] == "pack"


def test_build_claude_hook_stdout_capture_only_is_none() -> None:
    result = HookRunResult(
        hook="PostToolUse",
        session_id="s1",
        skipped=False,
        reason=None,
    )
    assert build_claude_hook_stdout(result, "postToolUse") is None
    assert build_claude_hook_stdout(result, "sessionEnd") is None


def test_cursor_stdout_unchanged() -> None:
    result = HookRunResult(
        hook="SessionStart",
        session_id="s1",
        skipped=False,
        reason=None,
        additional_context="pack",
    )
    out = build_cursor_hook_stdout(result, "sessionStart")
    assert out == {"additional_context": "pack"}


def test_run_install_claude_writes_settings_skill_rules(tmp_path: Path) -> None:
    result = run_install(tmp_path, dev=True, force=True, client="claude")
    settings = tmp_path / ".claude" / "settings.json"
    skill = tmp_path / ".claude" / "skills" / "brainkm-routing" / "SKILL.md"
    rule = tmp_path / ".claude" / "rules" / "brainkm.md"
    mcp = tmp_path / ".mcp.json"
    claude_md = tmp_path / "CLAUDE.md"

    assert settings in result.files_written or settings.is_file()
    assert settings.is_file()
    assert skill.is_file()
    assert rule.is_file()
    assert mcp.is_file()
    assert claude_md.is_file()
    assert not (tmp_path / ".claude" / "hooks.json").is_file()

    data = json.loads(settings.read_text(encoding="utf-8"))
    assert "SessionStart" in data["hooks"]
    cmd = data["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert "--client claude" in cmd
    assert "post-compact --stdin" in data["hooks"]["PostCompact"][0]["hooks"][0]["command"]

    cfg = load_brain_config(tmp_path)
    assert cfg.capture.auto_observe is True


def test_hooks_path_for_client_claude_is_settings() -> None:
    path = hooks_path_for_client(Path("/proj"), "claude")
    assert path == Path("/proj/.claude/settings.json")


def test_run_connect_claude_writes_settings(tmp_path: Path) -> None:
    (tmp_path / ".brain").mkdir()
    from brainkm.services.config_loader import save_brain_config

    save_brain_config(tmp_path, BrainConfig())
    result = run_connect("claude", tmp_path, transport="stdio", hooks=True, dev=True)
    settings = tmp_path / ".claude" / "settings.json"
    assert settings in result.files_written
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert "SubagentStop" in data["hooks"]
    cfg = load_brain_config(tmp_path)
    assert cfg.capture.auto_observe is True


def test_subagent_stop_and_agent_stop(tmp_path: Path) -> None:
    run_install(tmp_path, dev=True, force=True, client="claude")
    stop = run_subagent_stop(
        json.dumps({"session_id": "sub-1"}),
        project_dir=tmp_path,
    )
    assert stop.hook == "SubagentStop"
    assert stop.session_id == "sub-1"
    assert not stop.skipped

    agent = run_agent_stop(
        json.dumps({"session_id": "main-1", "reason": "user"}),
        project_dir=tmp_path,
    )
    assert agent.hook == "Stop"
    assert agent.session_id == "main-1"


def test_inspect_claude_wiring_warns_on_legacy_hooks_json(tmp_path: Path) -> None:
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "hooks.json").write_text('{"hooks": {}}\n', encoding="utf-8")
    notes = inspect_claude_wiring(tmp_path)
    assert any("Legacy .claude/hooks.json" in n for n in notes)
    assert any("settings.json" in n for n in notes)


def test_inspect_claude_wiring_warns_on_http_url_without_type(tmp_path: Path) -> None:
    (tmp_path / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "brainkm": {
                        "url": "http://127.0.0.1:8765/mcp/",
                        "headers": {"Authorization": "Bearer x"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    notes = inspect_claude_wiring(tmp_path)
    assert any('no "type": "http"' in n for n in notes)


def test_inspect_claude_wiring_accepts_settings_local_approval(tmp_path: Path) -> None:
    (tmp_path / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "brainkm": {
                        "type": "http",
                        "url": "http://127.0.0.1:8765/mcp/",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.local.json").write_text(
        json.dumps({"enabledMcpjsonServers": ["brainkm"]}),
        encoding="utf-8",
    )
    notes = inspect_claude_wiring(tmp_path)
    assert not any("enabledMcpjsonServers" in n for n in notes)
