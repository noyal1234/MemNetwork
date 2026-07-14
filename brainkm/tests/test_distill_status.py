"""Tests for unified distill-mode readiness status."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from brainkm.services.cursor_advisor import CursorStatus
from brainkm.services.distill_status import (
    DistillModeStatus,
    active_distill_display,
    build_distill_status,
    format_distill_status_line,
)
from brainkm.services.groq_advisor import GroqStatus
from brainkm.services.ollama_advisor import OllamaStatus


def test_build_distill_status_defaults(tmp_path: Path) -> None:
    brain_dir = tmp_path / ".brain"
    brain_dir.mkdir()
    (brain_dir / "config.json").write_text(
        json.dumps({"version": 1, "capture": {"distill_mode": "cursor"}}),
        encoding="utf-8",
    )
    with (
        patch(
            "brainkm.services.distill_status.probe_cursor_agent",
            return_value=CursorStatus(found=False),
        ),
        patch(
            "brainkm.services.distill_status.probe_ollama",
            return_value=OllamaStatus(reachable=False),
        ),
        patch(
            "brainkm.services.distill_status.probe_groq",
            return_value=GroqStatus(reachable=False, error="GROQ_API_KEY not set"),
        ),
    ):
        statuses = build_distill_status(project_dir=tmp_path)

    by_mode = {s.mode: s for s in statuses}
    assert by_mode["cursor"].ready is True
    assert by_mode["cursor"].is_default is True
    assert by_mode["cursor"].is_active is True
    assert "heuristic" in by_mode["cursor"].detail
    assert by_mode["rules"].ready is True
    assert by_mode["ollama"].ready is False
    assert by_mode["groq"].ready is False


def test_build_distill_status_with_agent_and_ollama(tmp_path: Path) -> None:
    brain_dir = tmp_path / ".brain"
    brain_dir.mkdir()
    (brain_dir / "config.json").write_text(
        json.dumps({"version": 1, "capture": {"distill_mode": "ollama"}}),
        encoding="utf-8",
    )
    with (
        patch(
            "brainkm.services.distill_status.probe_cursor_agent",
            return_value=CursorStatus(
                found=True, bin_path="/usr/bin/agent", bin_name="agent"
            ),
        ),
        patch(
            "brainkm.services.distill_status.probe_ollama",
            return_value=OllamaStatus(reachable=True, installed_models=("qwen2.5:3b",)),
        ),
        patch(
            "brainkm.services.distill_status.probe_groq",
            return_value=GroqStatus(reachable=True, models=("llama-3.3-70b-versatile",)),
        ),
    ):
        statuses = build_distill_status(project_dir=tmp_path)

    by_mode = {s.mode: s for s in statuses}
    assert by_mode["cursor"].detail.startswith("agent CLI")
    assert by_mode["ollama"].ready is True
    assert by_mode["ollama"].is_active is True
    assert by_mode["cursor"].is_active is False
    assert by_mode["groq"].ready is True


def test_format_distill_status_line() -> None:
    statuses = [
        DistillModeStatus(
            mode="cursor",
            ready=True,
            detail="heuristic active (no agent CLI)",
            is_default=True,
            is_active=True,
        ),
        DistillModeStatus(
            mode="rules",
            ready=True,
            detail="pattern-match offline",
            is_default=False,
        ),
        DistillModeStatus(
            mode="ollama",
            ready=False,
            detail="unreachable",
            is_default=False,
        ),
        DistillModeStatus(
            mode="groq",
            ready=False,
            detail="GROQ_API_KEY not set",
            is_default=False,
        ),
    ]
    line = format_distill_status_line(statuses)
    assert "cursor" in line
    # Inactive rules is omitted so the summary is not a peer-looking duplicate.
    assert "rules" not in line
    assert "ollama unreachable" in line
    assert "GROQ_API_KEY" in line or "groq" in line


def test_format_distill_status_line_includes_active_rules() -> None:
    statuses = [
        DistillModeStatus(
            mode="cursor",
            ready=True,
            detail="heuristic active (no agent CLI)",
            is_default=True,
            is_active=False,
        ),
        DistillModeStatus(
            mode="rules",
            ready=True,
            detail="pattern-match offline",
            is_default=False,
            is_active=True,
        ),
    ]
    line = format_distill_status_line(statuses)
    assert "rules OK" in line


def test_active_distill_display() -> None:
    statuses = [
        DistillModeStatus(
            mode="cursor",
            ready=True,
            detail="heuristic active (no agent CLI)",
            is_default=True,
            is_active=True,
        ),
        DistillModeStatus(
            mode="rules",
            ready=True,
            detail="pattern-match offline",
            is_default=False,
        ),
    ]
    mode, display, color = active_distill_display(statuses)
    assert mode == "cursor"
    assert "heuristic" in display
    assert color == "ok"
