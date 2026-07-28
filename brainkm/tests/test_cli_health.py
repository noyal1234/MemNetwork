"""Tests for CLI health breadcrumbs and SessionStart notice."""

from __future__ import annotations

import json
from pathlib import Path

from brainkm.services.cli_health import (
    clear_cli_health,
    cli_health_path,
    consume_cli_health_notice,
    doctor_cli_health_notes,
    read_cli_health,
)
from brainkm.services.hooks import run_session_start
from brainkm.models.brain_config import BrainConfig


def _write_health(project: Path, **payload: object) -> None:
    brain = project / ".brain"
    brain.mkdir(parents=True, exist_ok=True)
    (brain / "cli_health.json").write_text(json.dumps(payload) + "\n", encoding="utf-8")


def test_consume_healed_notice_clears_breadcrumb(tmp_path: Path) -> None:
    _write_health(
        tmp_path,
        status="healed",
        cleared_pth=2,
        fix="bash brainkm/scripts/repair_venv.sh",
    )
    notice = consume_cli_health_notice(tmp_path)
    assert notice is not None
    assert "auto-repaired" in notice
    assert "cleared 2" in notice
    assert read_cli_health(tmp_path) is None


def test_consume_broken_notice(tmp_path: Path) -> None:
    _write_health(
        tmp_path,
        status="broken",
        error="ModuleNotFoundError: brainkm.cli",
        fix="bash brainkm/scripts/repair_venv.sh",
    )
    notice = consume_cli_health_notice(tmp_path)
    assert notice is not None
    assert "CLI was broken" in notice
    assert "repair_venv" in notice
    assert not cli_health_path(tmp_path).exists()


def test_doctor_notes_broken_breadcrumb(tmp_path: Path) -> None:
    _write_health(tmp_path, status="broken", fix="bash brainkm/scripts/repair_venv.sh")
    notes = doctor_cli_health_notes(tmp_path)
    assert any("WARNING" in n and "broken" in n for n in notes)


def test_session_start_prepends_cli_health_notice(tmp_path: Path) -> None:
    _write_health(
        tmp_path,
        status="healed",
        cleared_pth=1,
        fix="bash brainkm/scripts/repair_venv.sh",
    )
    result = run_session_start(
        json.dumps({"session_id": "cli-health-sess"}),
        project_dir=tmp_path,
        config=BrainConfig(),
    )
    assert result.skipped is False
    assert result.additional_context is not None
    assert "auto-repaired" in result.additional_context
    assert read_cli_health(tmp_path) is None


def test_clear_cli_health_noop_when_missing(tmp_path: Path) -> None:
    clear_cli_health(tmp_path)
