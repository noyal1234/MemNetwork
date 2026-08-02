"""Parity tests for Cursor / Claude / Antigravity client wiring."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from typer.testing import CliRunner

from brainkm.cli import app
from brainkm.models.brain_config import BrainConfig
from brainkm.services.config_loader import save_brain_config
from brainkm.services.connect import run_connect
from brainkm.services.hooks import build_claude_hook_stdout, run_subagent_start
from brainkm.services.install import (
    build_antigravity_hooks_config,
    build_claude_hooks_config,
    build_codex_hooks_config,
    build_hooks_config,
    run_install,
    upsert_project_md_snippet,
)
from brainkm.services.mcp_doctor import (
    build_mcp_doctor_report,
    format_mcp_doctor_report,
    inspect_cursor_wiring,
)
from brainkm.services.mcp_transport import normalize_mcp_entry_transport_fields


def test_cursor_hooks_template_matches_builder() -> None:
    template = json.loads(
        resources.files("brainkm.hooks.cursor").joinpath("hooks.json").read_text(encoding="utf-8")
    )
    built = build_hooks_config("brainkm")
    assert template == built


def test_claude_hooks_template_matches_builder() -> None:
    template = json.loads(
        resources.files("brainkm.hooks.claude").joinpath("hooks.json").read_text(encoding="utf-8")
    )
    built = build_claude_hooks_config("brainkm")
    assert template == built


def test_antigravity_hooks_template_matches_builder() -> None:
    template = json.loads(
        resources.files("brainkm.hooks.antigravity")
        .joinpath("hooks.json")
        .read_text(encoding="utf-8")
    )
    built = build_antigravity_hooks_config("brainkm")
    assert template == built


def test_codex_hooks_template_matches_builder_parity() -> None:
    template = json.loads(
        resources.files("brainkm.hooks.codex").joinpath("hooks.json").read_text(encoding="utf-8")
    )
    built = build_codex_hooks_config("brainkm")
    assert template == built


def test_normalize_prefers_server_url_when_url_differs() -> None:
    entry = {
        "serverUrl": "http://127.0.0.1:8765/mcp/",
        "url": "http://127.0.0.1:9999/mcp",
        "command": "brainkm",
        "args": ["mcp"],
        "headers": {"Authorization": "Bearer tok"},
    }
    out = normalize_mcp_entry_transport_fields(entry)
    assert out["serverUrl"] == "http://127.0.0.1:8765/mcp/"
    assert out["type"] == "http"
    assert "url" not in out
    assert "command" not in out
    assert "args" not in out
    assert out["headers"]["Authorization"] == "Bearer tok"


def test_cursor_install_http_over_stdio_normalizes(tmp_path: Path) -> None:
    run_install(tmp_path, dev=True, force=True, client="cursor", no_graph=True)
    mcp_path = tmp_path / ".cursor" / "mcp.json"
    stdio = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert "command" in stdio["mcpServers"]["brainkm"]

    run_install(
        tmp_path,
        dev=True,
        force=True,
        client="cursor",
        no_graph=True,
        http=True,
    )
    entry = json.loads(mcp_path.read_text(encoding="utf-8"))["mcpServers"]["brainkm"]
    assert "url" in entry
    assert "command" not in entry
    assert "args" not in entry
    assert "Authorization" in entry.get("headers", {})


def test_connect_antigravity_http_writes_bearer(tmp_path: Path) -> None:
    run_install(
        project_dir=tmp_path,
        dev=True,
        force=True,
        no_graph=True,
        client="antigravity",
    )
    run_connect("antigravity", tmp_path, transport="http", hooks=True, dev=True)
    entry = json.loads((tmp_path / ".agents" / "mcp_config.json").read_text())["mcpServers"][
        "brainkm"
    ]
    assert entry.get("serverUrl") == "http://127.0.0.1:8765/mcp/"
    assert "command" not in entry
    headers = entry.get("headers") or {}
    assert str(headers.get("Authorization", "")).startswith("Bearer ")


def test_inspect_cursor_wiring_missing_user_prompt(tmp_path: Path) -> None:
    cursor = tmp_path / ".cursor"
    cursor.mkdir()
    (cursor / "mcp.json").write_text(
        json.dumps({"mcpServers": {"brainkm": {"command": "brainkm", "args": ["mcp"]}}}),
        encoding="utf-8",
    )
    (cursor / "hooks.json").write_text(
        json.dumps(
            {
                "version": 1,
                "hooks": {
                    "sessionStart": [{"command": "brainkm session-start --stdin"}],
                    "sessionEnd": [{"command": "brainkm session-end --stdin"}],
                    "preCompact": [{"command": "brainkm handover --stdin"}],
                    "preToolUse": [
                        {"matcher": "Write|Edit|Shell", "command": "brainkm pre-tool --stdin"}
                    ],
                    "postToolUse": [
                        {"matcher": "Write|Edit", "command": "brainkm post-tool --stdin"}
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    notes = inspect_cursor_wiring(tmp_path)
    assert any("beforeSubmitPrompt" in n for n in notes)
    assert any("Shell" in n for n in notes)
    # P7: stop is a real Cursor hook event (fires when the agent loop ends,
    # distinct from sessionEnd) and must be flagged missing like any other.
    assert any("stop" in n for n in notes)


def test_run_install_cursor_writes_stop_hook(tmp_path: Path) -> None:
    run_install(tmp_path, dev=True, force=True, client="cursor", no_graph=True)
    hooks = json.loads((tmp_path / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
    stop_entries = hooks["hooks"]["stop"]
    assert stop_entries
    assert "agent-stop" in stop_entries[0]["command"]
    assert "--client cursor" in stop_entries[0]["command"]


def test_doctor_report_uses_client_notes_label(tmp_path: Path) -> None:
    run_install(tmp_path, dev=True, force=True, client="cursor", no_graph=True)
    # Stale hooks on purpose
    hooks = tmp_path / ".cursor" / "hooks.json"
    data = json.loads(hooks.read_text(encoding="utf-8"))
    data["hooks"].pop("beforeSubmitPrompt", None)
    hooks.write_text(json.dumps(data), encoding="utf-8")

    report = build_mcp_doctor_report(tmp_path)
    assert report.client_notes
    assert report.claude_notes is report.client_notes  # alias
    text = format_mcp_doctor_report(report)
    assert "client notes:" in text
    assert "claude silent-memory:" not in text


def test_upsert_project_md_snippet_force_preserves_user_content(tmp_path: Path) -> None:
    path = tmp_path / "CLAUDE.md"
    path.write_text(
        "# My project\n\nKeep me.\n\n# brainkm — project memory routing\n\nold snippet\n",
        encoding="utf-8",
    )
    action = upsert_project_md_snippet(
        path,
        "# brainkm — project memory routing\n\nnew snippet\n",
        force=True,
    )
    assert action == "replaced"
    text = path.read_text(encoding="utf-8")
    assert "Keep me." in text
    assert "new snippet" in text
    assert "old snippet" not in text


def test_claude_install_force_does_not_clobber_claude_md(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text(
        "# User notes\n\nImportant.\n\n# brainkm — project memory routing\n\nold\n",
        encoding="utf-8",
    )
    run_install(tmp_path, dev=True, force=True, client="claude", no_graph=True)
    text = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Important." in text
    assert "brainkm — project memory routing" in text
    assert "old\n" not in text or "Important." in text


def test_subagent_start_injects_pack(tmp_path: Path) -> None:
    run_install(tmp_path, dev=True, force=True, client="claude", no_graph=True)
    result = run_subagent_start(
        json.dumps({"session_id": "sub-inject-1"}),
        project_dir=tmp_path,
    )
    assert result.hook == "SubagentStart"
    assert not result.skipped
    assert result.additional_context  # frozen pack text
    out = build_claude_hook_stdout(result, "subagentStart")
    assert out is not None
    assert out["hookSpecificOutput"]["hookEventName"] == "SubagentStart"
    assert out["hookSpecificOutput"]["additionalContext"] == result.additional_context


def test_cursor_session_end_failsoft_and_json_clean_stdout(tmp_path: Path) -> None:
    save_brain_config(tmp_path, BrainConfig())
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "session-end",
            "--stdin",
            "--client",
            "cursor",
            "--project-dir",
            str(tmp_path),
        ],
        input='{"session_id":"cursor-failsoft","transcript_path":"/no/such/file.jsonl"}\n',
    )
    # Fail-soft: exit 0 even when capture cannot find a transcript.
    assert result.exit_code == 0
    # Capture-only hooks must not print human-readable status on stdout.
    assert (result.stdout or "").strip() == ""
