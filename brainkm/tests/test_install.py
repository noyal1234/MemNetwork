"""Tests for brainkm install service."""

import json
from pathlib import Path

from brainkm.services.install import (
    build_hooks_config,
    build_mcp_config,
    merge_hooks_json,
    run_install,
)


def _settings_with_pretool_matcher(root: Path, matcher: str) -> Path:
    path = root / ".claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": matcher,
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "brainkm pre-tool --stdin --client claude",
                                }
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def test_ensure_claude_pretool_matcher_adds_missing_bash(tmp_path: Path) -> None:
    """A matcher predating the run_terminal default never fires on Bash."""
    from brainkm.services.install import ensure_claude_pretool_matcher

    path = _settings_with_pretool_matcher(tmp_path, "Write|Edit|Read|Grep|Glob")
    assert ensure_claude_pretool_matcher(tmp_path) is True
    matcher = json.loads(path.read_text())["hooks"]["PreToolUse"][0]["matcher"]
    assert "Bash" in matcher.split("|")
    # Idempotent: a healed file is not rewritten again.
    assert ensure_claude_pretool_matcher(tmp_path) is False


def test_ensure_claude_pretool_matcher_preserves_user_tokens(tmp_path: Path) -> None:
    """Heal only widens — hand-added matcher entries survive."""
    from brainkm.services.install import ensure_claude_pretool_matcher

    path = _settings_with_pretool_matcher(tmp_path, "Write|CustomTool")
    assert ensure_claude_pretool_matcher(tmp_path) is True
    tokens = json.loads(path.read_text())["hooks"]["PreToolUse"][0]["matcher"].split("|")
    assert "CustomTool" in tokens
    assert "Bash" in tokens


def test_ensure_claude_pretool_matcher_ignores_foreign_groups(tmp_path: Path) -> None:
    """Non-brainkm hook groups must not be touched."""
    from brainkm.services.install import ensure_claude_pretool_matcher

    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Write",
                            "hooks": [{"type": "command", "command": "other-tool check"}],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    assert ensure_claude_pretool_matcher(tmp_path) is False
    assert json.loads(path.read_text())["hooks"]["PreToolUse"][0]["matcher"] == "Write"


def test_build_mcp_config_dev_uses_local_binary() -> None:
    payload = build_mcp_config(dev=True)
    server = payload["mcpServers"]["brainkm"]
    assert server["args"] == ["mcp", "--project-dir", "."]
    assert str(server["command"]).endswith("brainkm")


def test_resolve_hook_command_dev_stays_in_venv_bin(tmp_path, monkeypatch) -> None:
    """Do not follow the venv python symlink into Homebrew Cellar."""
    from brainkm.services.install import resolve_hook_command

    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    python = venv_bin / "python"
    brainkm = venv_bin / "brainkm"
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    brainkm.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr("brainkm.services.install.sys.executable", str(python))
    resolved = resolve_hook_command(dev=True)
    assert resolved == str(brainkm)
    assert "Cellar" not in resolved


def test_build_mcp_config_prod_prefers_path_brainkm(monkeypatch) -> None:
    monkeypatch.setattr(
        "brainkm.services.install.shutil.which",
        lambda name: "/opt/bin/brainkm" if name == "brainkm" else None,
    )
    payload = build_mcp_config(dev=False)
    server = payload["mcpServers"]["brainkm"]
    assert server["command"] == "/opt/bin/brainkm"
    assert server["args"] == ["mcp", "--project-dir", "."]


def test_build_mcp_config_prod_falls_back_to_uvx_when_not_on_path(monkeypatch) -> None:
    """uvx placeholder remains for a future public PyPI release (currently deferred)."""
    monkeypatch.setattr("brainkm.services.install.shutil.which", lambda _name: None)
    payload = build_mcp_config(dev=False)
    server = payload["mcpServers"]["brainkm"]
    assert server["command"] == "uvx"
    assert server["args"] == ["brainkm@latest", "mcp", "--project-dir", "."]


def test_build_hooks_config_includes_all_events() -> None:
    hooks = build_hooks_config("/usr/local/bin/brainkm")
    events = hooks["hooks"]
    assert "sessionStart" in events
    assert "sessionEnd" in events
    assert "preCompact" in events
    assert "preToolUse" in events
    assert "postToolUse" in events
    assert "beforeSubmitPrompt" in events
    assert "postToolUseFailure" not in events
    assert "handover --stdin" in str(events["preCompact"])
    assert events["postToolUse"][0]["matcher"] == "Write|Edit|Shell"


def test_build_hooks_config_quotes_binary_with_spaces() -> None:
    hooks = build_hooks_config("/Users/dev/My Tools/brainkm")
    command = hooks["hooks"]["sessionStart"][0]["command"]
    assert command == (
        "'/Users/dev/My Tools/brainkm' session-start --stdin --client cursor"
    )


def test_gitignore_entries_cover_secrets() -> None:
    from brainkm.services.install import GITIGNORE_ENTRIES

    assert ".brain/mcp_http_token" in GITIGNORE_ENTRIES
    assert ".env" in GITIGNORE_ENTRIES
    assert ".brain/exports/" in GITIGNORE_ENTRIES


def test_merge_hooks_json_replaces_brainkm_commands() -> None:
    existing = {
        "version": 1,
        "hooks": {
            "sessionStart": [{"command": "/old/brainkm session-start --stdin"}],
            "preCompact": [{"command": "other-tool --run"}],
        },
    }
    incoming = build_hooks_config("/new/brainkm")
    merged = merge_hooks_json(existing, incoming)

    commands = [item["command"] for item in merged["hooks"]["sessionStart"]]
    assert commands == ["/new/brainkm session-start --stdin --client cursor"]
    assert merged["hooks"]["preCompact"][0]["command"] == "other-tool --run"
    assert any("handover --stdin" in item["command"] for item in merged["hooks"]["preCompact"])
    assert any("--client cursor" in item["command"] for item in merged["hooks"]["preCompact"])


def test_build_hooks_config_cursor_client_flag_and_pack_matcher() -> None:
    hooks = build_hooks_config("brainkm")
    events = hooks["hooks"]
    assert events["preToolUse"][0]["matcher"] == "Write|Edit|Shell"
    for key in ("sessionStart", "sessionEnd", "beforeSubmitPrompt"):
        assert "--client cursor" in events[key][0]["command"]
    assert "--client cursor" in events["preToolUse"][0]["command"]
    assert "Read|Grep|Glob" not in events["preToolUse"][0]["matcher"]


def test_merge_hooks_json_strips_unsupported_post_compact() -> None:
    existing = {
        "version": 1,
        "hooks": {
            "postCompact": [{"command": "brainkm post-compact --stdin"}],
            "sessionStart": [{"command": "brainkm session-start --stdin"}],
        },
    }
    incoming = build_hooks_config("/new/brainkm")
    merged = merge_hooks_json(existing, incoming)

    assert "postCompact" not in merged["hooks"]
    assert merged["hooks"]["sessionStart"]


def test_run_install_writes_cursor_and_brain_files(tmp_path: Path) -> None:
    result = run_install(tmp_path, dev=True, force=True)
    assert result.project_dir == tmp_path.resolve()

    mcp_path = tmp_path / ".cursor" / "mcp.json"
    hooks_path = tmp_path / ".cursor" / "hooks.json"
    rule_path = tmp_path / ".cursor" / "rules" / "brainkm.mdc"
    config_path = tmp_path / ".brain" / "config.json"
    db_path = tmp_path / ".brain" / "brain.db"
    calibration_path = tmp_path / ".brain" / "abstention_calibration.json"

    assert mcp_path.is_file()
    assert hooks_path.is_file()
    assert rule_path.is_file()
    assert config_path.is_file()
    assert db_path.is_file()
    assert calibration_path.is_file()

    mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert "brainkm" in mcp["mcpServers"]

    hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert "sessionStart" in hooks["hooks"]
    assert "sessionEnd" in hooks["hooks"]

    gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".brain/brain.db" in gitignore


def test_run_install_skips_existing_config_without_force(tmp_path: Path) -> None:
    brain_dir = tmp_path / ".brain"
    brain_dir.mkdir()
    # Explicit commit_trace so grandfathering does not force a rewrite.
    (brain_dir / "config.json").write_text(
        '{"version": 1, "git": {"commit_trace": false}}\n',
        encoding="utf-8",
    )

    result = run_install(tmp_path, dev=True, force=False)
    assert tmp_path / ".brain" / "config.json" in result.files_skipped
