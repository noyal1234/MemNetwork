"""Tests for the Actions screen — service invocations + log output."""

from __future__ import annotations

from pathlib import Path

import pytest

from brainkm.tui.app import BrainkmConfigureApp
from brainkm.tui.widgets.rich_log_panel import RichLogPanel


@pytest.mark.parametrize(
    "button_id",
    [
        "btn-graph-sync",
        "btn-graph-status",
        "btn-ollama-doctor",
        "btn-groq-doctor",
        "btn-export",
        "btn-repair",
        "btn-bench-token",
    ],
)
async def test_action_button_does_not_crash(tui_project: Path, button_id: str) -> None:
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(140, 60)) as pilot:
        app.switch_screen("actions")
        await pilot.pause(0.3)
        await pilot.click(f"#{button_id}")
        await pilot.pause(1.5)
        assert app.screen is not None


async def test_action_button_writes_to_log(tui_project: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(140, 60)) as pilot:
        app.switch_screen("actions")
        await pilot.pause(0.3)
        await pilot.click("#btn-graph-status")
        await pilot.pause(2.0)
        log = app.screen.query_one("#action-log", RichLogPanel)
        assert len(log.rich_log.lines) >= 2


async def test_export_writes_to_this_projects_brain_dir(tui_project: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(140, 60)) as pilot:
        app.switch_screen("actions")
        await pilot.pause(0.3)
        await pilot.click("#btn-export")
        await pilot.pause(1.0)
        exports_dir = tui_project / ".brain" / "exports"
        assert exports_dir.is_dir()
        assert list(exports_dir.glob("*.md"))
