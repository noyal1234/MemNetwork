"""Tests for serve_helper (background shared brain)."""

from __future__ import annotations

from pathlib import Path

from brainkm.db.migrate import migrate
from brainkm.models.brain_config import BrainConfig, McpConfig
from brainkm.services.config_loader import save_brain_config
from brainkm.services.serve_helper import get_serve_status, serve_pid_path


def test_get_serve_status_stdio_project(tmp_path: Path) -> None:
    migrate(project_dir=tmp_path, run_integrity_check=False)
    save_brain_config(tmp_path, BrainConfig())
    status = get_serve_status(tmp_path)
    assert status.transport == "stdio"
    assert status.running is False
    assert serve_pid_path(tmp_path).name == "serve.pid"


def test_get_serve_status_http_not_running(tmp_path: Path) -> None:
    migrate(project_dir=tmp_path, run_integrity_check=False)
    save_brain_config(
        tmp_path,
        BrainConfig(mcp=McpConfig(transport="http", http_port=18765)),
    )
    status = get_serve_status(tmp_path)
    assert status.transport == "http"
    assert status.running is False
