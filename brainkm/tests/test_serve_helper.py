"""Tests for serve_helper (background shared brain)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from brainkm import __version__
from brainkm.db.migrate import migrate
from brainkm.models.brain_config import BrainConfig, McpConfig
from brainkm.services.config_loader import save_brain_config
from brainkm.services.serve_helper import (
    ServeStatus,
    get_serve_status,
    parse_health_version,
    restart_serve_background,
    serve_pid_path,
    start_serve_background,
)


def test_parse_health_version() -> None:
    assert parse_health_version('{"ok":true,"version":"0.8.5"}') == "0.8.5"
    assert parse_health_version("unreachable: refuse") is None
    assert parse_health_version("{not-json") is None


def test_get_serve_status_stdio_project(tmp_path: Path) -> None:
    migrate(project_dir=tmp_path, run_integrity_check=False)
    save_brain_config(tmp_path, BrainConfig())
    status = get_serve_status(tmp_path)
    assert status.transport == "stdio"
    assert status.running is False
    assert status.version_mismatch is False
    assert status.package_version == __version__
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
    assert status.version_mismatch is False


def test_get_serve_status_detects_version_mismatch(tmp_path: Path) -> None:
    migrate(project_dir=tmp_path, run_integrity_check=False)
    save_brain_config(
        tmp_path,
        BrainConfig(mcp=McpConfig(transport="http", http_port=18766)),
    )
    stale = f'{{"ok":true,"version":"0.0.1"}}'
    with patch(
        "brainkm.services.serve_helper.probe_health",
        return_value=(True, stale),
    ):
        status = get_serve_status(tmp_path)
    assert status.running is True
    assert status.serve_version == "0.0.1"
    assert status.package_version == __version__
    assert status.version_mismatch is True


def test_start_serve_force_restarts_on_mismatch(tmp_path: Path) -> None:
    migrate(project_dir=tmp_path, run_integrity_check=False)
    save_brain_config(
        tmp_path,
        BrainConfig(mcp=McpConfig(transport="http", http_port=18767)),
    )
    calls: list[str] = []

    def fake_get(_project_dir=None):
        # First call: stale running; after stop+start: healthy matching.
        if "stop" in calls and "start_spawn" in calls:
            return ServeStatus(
                running=True,
                health_url="http://127.0.0.1:18767/health",
                detail=f'{{"ok":true,"version":"{__version__}"}}',
                transport="http",
                pid_file=serve_pid_path(tmp_path),
                serve_version=__version__,
                package_version=__version__,
                version_mismatch=False,
            )
        return ServeStatus(
            running=True,
            health_url="http://127.0.0.1:18767/health",
            detail='{"ok":true,"version":"0.0.1"}',
            transport="http",
            pid_file=serve_pid_path(tmp_path),
            serve_version="0.0.1",
            package_version=__version__,
            version_mismatch=True,
        )

    def fake_stop(_project_dir=None):
        calls.append("stop")
        return True

    def fake_popen(*_a, **_k):
        calls.append("start_spawn")

        class _Proc:
            pid = 4242

        return _Proc()

    with (
        patch("brainkm.services.serve_helper.get_serve_status", side_effect=fake_get),
        patch("brainkm.services.serve_helper.stop_serve_background", side_effect=fake_stop),
        patch("brainkm.services.serve_helper.subprocess.Popen", side_effect=fake_popen),
        patch("brainkm.services.serve_helper.time.sleep", return_value=None),
        patch("brainkm.services.serve_helper.resolve_hook_command", return_value="brainkm"),
    ):
        # Path(brainkm_bin).exists() — force the python -m fallback or pretend exists
        with patch("brainkm.services.serve_helper.Path.exists", return_value=True):
            status = start_serve_background(tmp_path, force=False)
    assert "stop" in calls
    assert "start_spawn" in calls
    assert status.version_mismatch is False


def test_restart_serve_background_calls_stop_then_start(tmp_path: Path) -> None:
    migrate(project_dir=tmp_path, run_integrity_check=False)
    save_brain_config(
        tmp_path,
        BrainConfig(mcp=McpConfig(transport="http", http_port=18768)),
    )
    calls: list[str] = []

    def fake_stop(_project_dir=None):
        calls.append("stop")
        return True

    def fake_start(*_a, **kwargs):
        calls.append(f"start:force={kwargs.get('force')}")
        return ServeStatus(
            running=True,
            health_url="http://127.0.0.1:18768/health",
            detail=f'{{"ok":true,"version":"{__version__}"}}',
            transport="http",
            pid_file=serve_pid_path(tmp_path),
            serve_version=__version__,
            package_version=__version__,
            version_mismatch=False,
        )

    with (
        patch("brainkm.services.serve_helper.stop_serve_background", side_effect=fake_stop),
        patch("brainkm.services.serve_helper.start_serve_background", side_effect=fake_start),
        patch("brainkm.services.serve_helper._wait_until_stopped", return_value=None),
    ):
        status = restart_serve_background(tmp_path, dev=True)
    assert calls == ["stop", "start:force=True"]
    assert status.running is True
