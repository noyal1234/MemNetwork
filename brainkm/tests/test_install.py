"""Tests for brainkm install service."""

import json
from pathlib import Path

from brainkm.services.install import (
    build_hooks_config,
    build_mcp_config,
    merge_hooks_json,
    run_install,
)


def test_build_mcp_config_dev_uses_local_binary() -> None:
    payload = build_mcp_config(dev=True)
    server = payload["mcpServers"]["brainkm"]
    assert server["args"] == ["mcp", "--project-dir", "."]
    assert str(server["command"]).endswith("brainkm")


def test_build_mcp_config_prod_uses_uvx() -> None:
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
    assert "handover --stdin" in str(events["preCompact"])


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
    assert commands == ["/new/brainkm session-start --stdin"]
    assert merged["hooks"]["preCompact"][0]["command"] == "other-tool --run"
    assert any(
        "handover --stdin" in item["command"] for item in merged["hooks"]["preCompact"]
    )


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
    (brain_dir / "config.json").write_text('{"version": 1}\n', encoding="utf-8")

    result = run_install(tmp_path, dev=True, force=False)
    assert tmp_path / ".brain" / "config.json" in result.files_skipped
