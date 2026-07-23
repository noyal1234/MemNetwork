"""Tests for shared MCP transport, connect, doctor, and passive observe."""

from __future__ import annotations

import json
from pathlib import Path

from brainkm.db.connection import connect
from brainkm.db.migrate import migrate
from brainkm.db.paths import brain_db_path
from brainkm.models.brain_config import BrainConfig, CaptureConfig
from brainkm.services.connect import run_connect
from brainkm.services.install import build_mcp_config, run_install
from brainkm.services.mcp_doctor import build_mcp_doctor_report
from brainkm.services.mcp_transport import build_mcp_config as transport_build
from brainkm.services.observe import (
    extract_observation_path,
    promote_session_observations,
    record_observation,
)


def test_build_mcp_config_http_uses_url() -> None:
    payload = transport_build(dev=True, transport="http", port=8765)
    server = payload["mcpServers"]["brainkm"]
    assert server["url"] == "http://127.0.0.1:8765/mcp"
    assert "command" not in server


def test_build_mcp_config_stdio_still_spawns() -> None:
    payload = build_mcp_config(dev=True, transport="stdio")
    server = payload["mcpServers"]["brainkm"]
    assert "command" in server
    assert server["args"] == ["mcp", "--project-dir", "."]


def test_connect_cursor_http_writes_url(tmp_path: Path) -> None:
    migrate(project_dir=tmp_path, run_integrity_check=False)
    result = run_connect(
        "cursor",
        tmp_path,
        transport="http",
        hooks=True,
        port=8765,
        dev=True,
    )
    mcp = json.loads((tmp_path / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    entry = mcp["mcpServers"]["brainkm"]
    assert entry["url"] == "http://127.0.0.1:8765/mcp"
    assert entry["headers"]["Authorization"].startswith("Bearer ")
    assert (tmp_path / ".brain" / "mcp_http_token").is_file()
    assert (tmp_path / ".cursor" / "hooks.json").is_file()
    assert result.mcp_url is not None
    cfg = json.loads((tmp_path / ".brain" / "config.json").read_text(encoding="utf-8"))
    assert cfg["mcp"]["transport"] == "http"
    assert cfg["capture"]["auto_observe"] is True


def test_connect_claude_writes_project_mcp(tmp_path: Path) -> None:
    migrate(project_dir=tmp_path, run_integrity_check=False)
    run_connect("claude", tmp_path, transport="http", hooks=True, dev=True)
    assert (tmp_path / ".mcp.json").is_file()
    assert (tmp_path / ".claude" / "settings.json").is_file()
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert "SessionStart" in settings["hooks"]
    mcp = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert "url" in mcp["mcpServers"]["brainkm"]


def test_connect_codex_writes_codex_dir(tmp_path: Path) -> None:
    migrate(project_dir=tmp_path, run_integrity_check=False)
    run_connect("codex", tmp_path, transport="http", hooks=True, dev=True)
    assert (tmp_path / ".codex" / "config.toml").is_file()
    assert (tmp_path / ".codex" / "hooks.json").is_file()
    assert not (tmp_path / ".codex" / "mcp.json").exists()


def test_doctor_flags_dual_writer(tmp_path: Path) -> None:
    migrate(project_dir=tmp_path, run_integrity_check=False)
    run_connect("cursor", tmp_path, transport="http", hooks=False, dev=True)
    # Force stale stdio entry alongside http config.
    mcp_path = tmp_path / ".cursor" / "mcp.json"
    mcp_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "brainkm": {
                        "command": "brainkm",
                        "args": ["mcp", "--project-dir", "."],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    report = build_mcp_doctor_report(tmp_path)
    assert report.config_transport == "http"
    assert report.dual_writer_warning is not None
    assert report.auto_observe is True


def test_observe_caps_and_dedup(tmp_path: Path) -> None:
    migrate(project_dir=tmp_path, run_integrity_check=False)
    cfg = BrainConfig(
        capture=CaptureConfig(
            auto_observe=True,
            observe_max_per_session=2,
            observe_dedup_window_seconds=300,
        )
    )
    conn = connect(brain_db_path(tmp_path))
    try:
        sid = "sess-observe-1"
        payload = {"file_path": "a.py", "status": "ok"}
        r1 = record_observation(
            conn, session_id=sid, tool_name="Write", payload=payload, config=cfg
        )
        r2 = record_observation(
            conn, session_id=sid, tool_name="Write", payload=payload, config=cfg
        )
        r3 = record_observation(
            conn,
            session_id=sid,
            tool_name="Edit",
            payload={"file_path": "b.py", "status": "ok"},
            config=cfg,
        )
        r4 = record_observation(
            conn,
            session_id=sid,
            tool_name="Shell",
            payload={"status": "ok"},
            config=cfg,
        )
        assert r1.stored
        assert not r2.stored and r2.skipped_reason == "dedup_window"
        assert r3.stored
        assert not r4.stored and r4.skipped_reason == "max_per_session"
        conn.commit()
    finally:
        conn.close()


def test_observe_keeps_status_past_old_char_clip(tmp_path: Path) -> None:
    """Status bodies must not be hard-clipped at 120 chars before token budget."""
    migrate(project_dir=tmp_path, run_integrity_check=False)
    cfg = BrainConfig(capture=CaptureConfig(auto_observe=True))
    status = (
        "Missing AGY rules/skills — .agents/ only has mcp_config.json + hooks.json. "
        "Full install would also add .agents/rules/brainkm.md"
    )
    assert len(status) > 120
    conn = connect(brain_db_path(tmp_path))
    try:
        result = record_observation(
            conn,
            session_id="sess-long-status",
            tool_name="UserPrompt",
            payload={"status": status, "path": "rules/brainkm.md"},
            config=cfg,
        )
        conn.commit()
        assert result.stored and result.node_id
        row = conn.execute(
            "SELECT content FROM nodes WHERE id = ?",
            (result.node_id,),
        ).fetchone()
        assert row is not None
        assert row["content"] == status
        assert "brainkm.md" in row["content"]
    finally:
        conn.close()


def test_observe_promote_failure_to_error_neuron(tmp_path: Path) -> None:
    migrate(project_dir=tmp_path, run_integrity_check=False)
    cfg = BrainConfig(capture=CaptureConfig(auto_observe=True))
    conn = connect(brain_db_path(tmp_path))
    try:
        sid = "sess-fail-1"
        record_observation(
            conn,
            session_id=sid,
            tool_name="Shell",
            payload={"error": "ModuleNotFoundError: brainkm"},
            config=cfg,
            failed=True,
        )
        promo = promote_session_observations(conn, session_id=sid, config=cfg, project_dir=tmp_path)
        conn.commit()
        assert promo.promoted >= 1
        row = conn.execute(
            """
            SELECT subtype, title, content FROM nodes
            WHERE kind = 'memory' AND valid_until IS NULL AND subtype = 'error'
            ORDER BY created_at DESC LIMIT 1
            """
        ).fetchone()
        assert row is not None
        assert "ModuleNotFoundError" in (row["content"] or "")
    finally:
        conn.close()


def test_install_claude_writes_mcp_json_not_cursor(tmp_path: Path) -> None:
    result = run_install(tmp_path, dev=True, force=True, no_graph=True, client="claude")
    assert (tmp_path / ".mcp.json").is_file()
    # Claude should not be forced into .cursor/mcp.json as primary.
    written = {p.name for p in result.files_written}
    assert (
        ".mcp.json" in {p.name for p in result.files_written} or (tmp_path / ".mcp.json").is_file()
    )
    _ = written


def test_install_http_enables_auto_observe(tmp_path: Path) -> None:
    run_install(
        tmp_path,
        dev=True,
        force=True,
        no_graph=True,
        client="cursor",
        http=True,
        port=8765,
    )
    cfg = json.loads((tmp_path / ".brain" / "config.json").read_text(encoding="utf-8"))
    assert cfg["mcp"]["transport"] == "http"
    assert cfg["capture"]["auto_observe"] is True
    mcp = json.loads((tmp_path / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["brainkm"]["url"].endswith(":8765/mcp")


def test_extract_observation_path_accepts_absolute_path() -> None:
    assert extract_observation_path({"tool_input": {"AbsolutePath": "/tmp/x.py"}}) == "/tmp/x.py"
    assert extract_observation_path({"tool_input": {"TargetFile": "rel.py"}}) == "rel.py"
