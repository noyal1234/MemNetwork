"""Tests for brainkm uninstall — subtractive teardown of install's wiring."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from brainkm.services.install import run_install
from brainkm.services.uninstall import remove_project_md_snippet, run_uninstall


def _install(tmp_path: Path, client: str) -> None:
    run_install(project_dir=tmp_path, dev=True, no_graph=True, client=client)


@pytest.mark.parametrize("client", ["cursor", "claude", "antigravity", "codex"])
def test_uninstall_removes_client_wiring(tmp_path: Path, client: str) -> None:
    """Install then uninstall leaves no brainkm MCP entry or hook command behind."""
    _install(tmp_path, client)
    result = run_uninstall(project_dir=tmp_path, clients=[client])

    assert result.changed
    for path in tmp_path.rglob("*"):
        if not path.is_file() or path.is_relative_to(tmp_path / ".brain"):
            continue
        if path.suffix not in (".json", ".toml", ".md", ".mdc"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert "brainkm" not in text, f"{path} still references brainkm"


def test_uninstall_keeps_brain_by_default_and_purges_on_request(tmp_path: Path) -> None:
    _install(tmp_path, "cursor")
    brain = tmp_path / ".brain"
    assert brain.is_dir()

    run_uninstall(project_dir=tmp_path, clients=["cursor"])
    assert brain.is_dir(), ".brain/ is user data — must survive a plain uninstall"

    result = run_uninstall(project_dir=tmp_path, clients=["cursor"], purge=True)
    assert result.purged
    assert not brain.exists()


def test_uninstall_preserves_foreign_mcp_servers_and_hooks(tmp_path: Path) -> None:
    """Only brainkm keys are stripped — other servers/hooks in shared files stay."""
    _install(tmp_path, "cursor")

    mcp_path = tmp_path / ".cursor" / "mcp.json"
    mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
    mcp["mcpServers"]["other"] = {"command": "other-server"}
    mcp_path.write_text(json.dumps(mcp), encoding="utf-8")

    hooks_path = tmp_path / ".cursor" / "hooks.json"
    hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
    hooks["hooks"]["sessionStart"].append({"command": "other-tool session-start"})
    hooks_path.write_text(json.dumps(hooks), encoding="utf-8")

    run_uninstall(project_dir=tmp_path, clients=["cursor"])

    mcp_after = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert mcp_after["mcpServers"] == {"other": {"command": "other-server"}}
    hooks_after = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert hooks_after["hooks"]["sessionStart"] == [{"command": "other-tool session-start"}]


def test_uninstall_removes_brainkm_only_files(tmp_path: Path) -> None:
    """A config file containing nothing but brainkm entries is deleted, not left empty."""
    _install(tmp_path, "cursor")
    run_uninstall(project_dir=tmp_path, clients=["cursor"])

    assert not (tmp_path / ".cursor" / "mcp.json").exists()
    assert not (tmp_path / ".cursor" / "hooks.json").exists()
    assert not (tmp_path / ".cursor" / "rules" / "brainkm.mdc").exists()
    assert not (tmp_path / ".cursor" / "skills" / "brainkm-routing").exists()


def test_uninstall_claude_strips_settings_and_permissions(tmp_path: Path) -> None:
    _install(tmp_path, "claude")
    settings = tmp_path / ".claude" / "settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["statusLine"] = {"type": "command", "command": "mine"}
    data["hooks"]["SessionStart"].append(
        {"matcher": "startup", "hooks": [{"type": "command", "command": "other-tool"}]}
    )
    settings.write_text(json.dumps(data), encoding="utf-8")

    run_uninstall(project_dir=tmp_path, clients=["claude"])

    after = json.loads(settings.read_text(encoding="utf-8"))
    assert after["statusLine"] == {"type": "command", "command": "mine"}
    assert after["hooks"]["SessionStart"] == [
        {"matcher": "startup", "hooks": [{"type": "command", "command": "other-tool"}]}
    ]
    assert not (tmp_path / ".claude" / "settings.local.json").exists()
    assert not (tmp_path / ".mcp.json").exists()


def test_uninstall_dry_run_changes_nothing(tmp_path: Path) -> None:
    _install(tmp_path, "cursor")
    before = {
        path: path.read_bytes()
        for path in sorted(tmp_path.rglob("*"))
        if path.is_file() and not path.is_relative_to(tmp_path / ".brain")
    }

    result = run_uninstall(project_dir=tmp_path, clients=["cursor"], purge=True, dry_run=True)

    assert result.dry_run
    assert result.files_removed, "dry run should still report what it would remove"
    after = {
        path: path.read_bytes()
        for path in sorted(tmp_path.rglob("*"))
        if path.is_file() and not path.is_relative_to(tmp_path / ".brain")
    }
    assert after == before
    assert (tmp_path / ".brain").is_dir()


def test_uninstall_auto_detects_wired_clients(tmp_path: Path) -> None:
    _install(tmp_path, "cursor")
    _install(tmp_path, "claude")

    result = run_uninstall(project_dir=tmp_path)

    assert set(result.clients) >= {"cursor", "claude"}
    assert not (tmp_path / ".cursor" / "mcp.json").exists()
    assert not (tmp_path / ".mcp.json").exists()


def test_uninstall_partial_keeps_shared_state_and_warns(tmp_path: Path) -> None:
    """Unwiring one of two clients must not tear down git hooks or .brain/."""
    _install(tmp_path, "cursor")
    _install(tmp_path, "claude")

    result = run_uninstall(project_dir=tmp_path, clients=["cursor"])

    assert any("still wired" in warning for warning in result.warnings)
    assert (tmp_path / ".mcp.json").is_file()
    assert (tmp_path / ".brain").is_dir()


def test_uninstall_rejects_unknown_client(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown client"):
        run_uninstall(project_dir=tmp_path, clients=["emacs"])


def test_uninstall_on_clean_project_warns(tmp_path: Path) -> None:
    result = run_uninstall(project_dir=tmp_path)
    assert not result.changed
    assert any("nothing to remove" in warning for warning in result.warnings)


# ---------------------------------------------------------------------------
# Project-md snippet surgery
# ---------------------------------------------------------------------------


def test_remove_project_md_snippet_keeps_surrounding_sections() -> None:
    text = (
        "# House rules\n\nAlways run tests.\n\n"
        "# brainkm — project memory routing\n\nUse recall.\n\n"
        "## Coexistence\n\nDetails.\n\n"
        "# Deploy\n\nShip it.\n"
    )
    out = remove_project_md_snippet(text)
    assert out is not None
    assert "brainkm" not in out
    assert "# House rules" in out
    assert "# Deploy" in out
    assert "Ship it." in out


def test_remove_project_md_snippet_absent_returns_none() -> None:
    assert remove_project_md_snippet("# Only mine\n\nnothing here\n") is None


def test_remove_project_md_snippet_trailing_section() -> None:
    text = "# Mine\n\nkeep\n\n# brainkm — project memory routing\n\nUse recall.\n"
    out = remove_project_md_snippet(text)
    assert out == "# Mine\n\nkeep\n"
