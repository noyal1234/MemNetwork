"""Tests for the first-run Wizard screen."""

from __future__ import annotations

import json
from pathlib import Path

from brainkm.tui.app import BrainkmConfigureApp
from brainkm.tui.screens.wizard import STEP_DISTILL, STEP_INSTALL, STEP_PROJECT


async def test_wizard_is_initial_screen_for_fresh_project(tmp_path: Path) -> None:
    """`_check_project` (step 0) is purely informational and auto-advances
    on mount, so a fresh wizard lands on step 1 (install) almost
    immediately."""
    app = BrainkmConfigureApp(project_dir=tmp_path)
    async with app.run_test(size=(140, 70)) as pilot:
        await pilot.pause(0.3)
        screen = app.screen
        assert screen._current_step == 1


async def test_wizard_install_step_scaffolds_project(tmp_path: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tmp_path)
    async with app.run_test(size=(140, 70)) as pilot:
        await pilot.pause(0.3)
        assert app.screen._current_step == 1  # auto-advanced past step 0

        await pilot.click("#btn-wizard-run")  # runs install
        await pilot.pause(2.0)

        screen = app.screen
        assert screen._current_step == 2
        assert (tmp_path / ".brain").is_dir()


async def test_wizard_distill_mode_selection_writes_config(tmp_path: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tmp_path)
    async with app.run_test(size=(140, 70)) as pilot:
        await pilot.pause(0.3)
        assert app.screen._current_step == 1

        for _ in range(2):  # install -> doctor
            await pilot.click("#btn-wizard-run")
            await pilot.pause(1.5)

        screen = app.screen
        assert screen._current_step == 3  # distill mode step
        assert screen._distill_mode == "cursor"  # default

        from textual.widgets import RadioSet

        radio_set = screen.query_one("#wizard-distill-radio", RadioSet)
        radio_set.focus()
        # Order: cursor (0), rules (1), ollama (2) — two next presses land on ollama
        radio_set.action_next_button()
        radio_set.action_next_button()
        radio_set.action_toggle_button()
        await pilot.pause(0.1)

        await pilot.click("#btn-wizard-run")
        await pilot.pause(0.5)

        cfg_path = tmp_path / ".brain" / "config.json"
        saved = json.loads(cfg_path.read_text())
        assert saved["capture"]["distill_mode"] == "ollama"
        assert screen._current_step == 4


async def test_wizard_skip_advances_without_running(tmp_path: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tmp_path)
    async with app.run_test(size=(140, 70)) as pilot:
        await pilot.pause(0.3)
        assert app.screen._current_step == 1

        await pilot.click("#btn-wizard-skip")
        await pilot.pause(0.2)
        assert app.screen._current_step == 2


def test_wizard_step_ids_are_unique() -> None:
    from brainkm.tui.screens.wizard import STEPS

    assert len(STEPS) == len(set(STEPS))
    assert STEP_PROJECT in STEPS
    assert STEP_INSTALL in STEPS
    assert STEP_DISTILL in STEPS
