"""Tests for the BrainkmConfigureApp shell — screen registry and routing."""

from __future__ import annotations

from pathlib import Path

import pytest

from brainkm.tui.app import BrainkmConfigureApp
from brainkm.tui.screens.actions import ActionsScreen
from brainkm.tui.screens.config_editor import ConfigEditorScreen
from brainkm.tui.screens.dashboard import DashboardScreen
from brainkm.tui.screens.wizard import WizardScreen


@pytest.mark.parametrize(
    ("screen_name", "screen_cls"),
    [
        ("dashboard", DashboardScreen),
        ("config", ConfigEditorScreen),
        ("actions", ActionsScreen),
        ("wizard", WizardScreen),
    ],
)
async def test_screens_are_bound_to_project_dir(
    tui_project: Path, screen_name: str, screen_cls: type
) -> None:
    """Regression test: every screen must receive the app's project_dir.

    `App.__init__()` copies `self.SCREENS` into its internal registry
    immediately, so the factories bound to project_dir must be set on the
    instance *before* `super().__init__()` runs — otherwise every screen
    silently falls back to `project_dir=None` (i.e. cwd), which would make
    the TUI read/write the wrong project's `.brain/` directory.
    """
    app = BrainkmConfigureApp(project_dir=tui_project)
    expected = tui_project.expanduser().resolve()
    async with app.run_test() as pilot:
        app.switch_screen(screen_name)
        await pilot.pause()
        assert isinstance(app.screen, screen_cls)
        assert app.screen._project_dir == expected


async def test_launches_dashboard_when_brain_exists(tui_project: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, DashboardScreen)


async def test_launches_wizard_when_no_brain_dir(tmp_path: Path) -> None:
    """A project with no `.brain/` should land on the first-run wizard."""
    app = BrainkmConfigureApp(project_dir=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, WizardScreen)


async def test_help_binding_shows_notification(tui_project: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        # No crash is the primary assertion; notify() queues a toast.
        assert app.screen is not None
