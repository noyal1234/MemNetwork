"""Tests for the first-run Wizard screen."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from brainkm.tui.app import BrainkmConfigureApp
from brainkm.tui.screens.wizard import (
    STEP_APIKEY,
    STEP_CURSOR_CLI,
    STEP_DISTILL,
    STEP_INSTALL,
    STEP_PROJECT,
    STEP_VIZ_LLM,
    STEPS,
)


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
        # Order: cursor (0), ollama (1), groq (2) — one next press lands on ollama
        radio_set.action_next_button()
        radio_set.action_toggle_button()
        await pilot.pause(0.1)

        await pilot.click("#btn-wizard-run")
        await pilot.pause(0.5)

        cfg_path = tmp_path / ".brain" / "config.json"
        saved = json.loads(cfg_path.read_text())
        assert saved["capture"]["distill_mode"] == "ollama"
        # Agent CLI is skipped for non-cursor modes → land on API key
        assert screen._current_step == 5
        assert STEPS[screen._current_step] == STEP_APIKEY


async def test_wizard_cursor_cli_skip_advances(tmp_path: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tmp_path)
    async with app.run_test(size=(140, 70)) as pilot:
        await pilot.pause(0.3)
        # install, doctor, distill (default cursor)
        for _ in range(3):
            await pilot.click("#btn-wizard-run")
            await pilot.pause(1.5)

        screen = app.screen
        assert STEPS[screen._current_step] == STEP_CURSOR_CLI

        await pilot.click("#btn-wizard-skip")
        await pilot.pause(0.2)
        assert screen._current_step == 5  # API key


async def test_wizard_cursor_cli_run_with_mocked_install(tmp_path: Path) -> None:
    from brainkm.services.cursor_advisor import CursorInstallResult, CursorStatus

    app = BrainkmConfigureApp(project_dir=tmp_path)
    async with app.run_test(size=(140, 70)) as pilot:
        await pilot.pause(0.3)
        for _ in range(3):
            await pilot.click("#btn-wizard-run")
            await pilot.pause(1.5)

        screen = app.screen
        assert STEPS[screen._current_step] == STEP_CURSOR_CLI

        with (
            patch(
                "brainkm.services.cursor_advisor.probe_cursor_agent",
                side_effect=[
                    CursorStatus(found=False),
                    CursorStatus(
                        found=True,
                        bin_path="/tmp/fake-agent",
                        bin_name="agent",
                    ),
                    CursorStatus(
                        found=True,
                        bin_path="/tmp/fake-agent",
                        bin_name="agent",
                    ),
                ],
            ),
            patch(
                "brainkm.services.cursor_advisor.install_cursor_agent_cli",
                return_value=CursorInstallResult(
                    ok=True,
                    found=True,
                    bin_path="/tmp/fake-agent",
                    stdout_tail="ok",
                ),
            ),
        ):
            await pilot.click("#btn-wizard-run")
            await pilot.pause(1.5)

        assert screen._current_step == 5  # advanced past cursor CLI


async def test_wizard_skip_advances_without_running(tmp_path: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tmp_path)
    async with app.run_test(size=(140, 70)) as pilot:
        await pilot.pause(0.3)
        assert app.screen._current_step == 1

        await pilot.click("#btn-wizard-skip")
        await pilot.pause(0.2)
        assert app.screen._current_step == 2


def test_wizard_step_ids_are_unique() -> None:
    assert len(STEPS) == len(set(STEPS))
    assert STEP_PROJECT in STEPS
    assert STEP_INSTALL in STEPS
    assert STEP_DISTILL in STEPS
    assert STEP_CURSOR_CLI in STEPS
    assert STEP_VIZ_LLM in STEPS
    assert STEPS.index(STEP_CURSOR_CLI) == STEPS.index(STEP_DISTILL) + 1
    assert STEPS[-2] == STEP_VIZ_LLM
    assert STEPS[-1] == "step-done"


async def test_wizard_viz_llm_skip_advances(tmp_path: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tmp_path)
    async with app.run_test(size=(140, 70)) as pilot:
        await pilot.pause(0.3)
        screen = app.screen
        screen._current_step = STEPS.index(STEP_VIZ_LLM)
        screen._update_step_visibility()
        await pilot.pause(0.1)

        await pilot.click("#btn-wizard-skip")
        await pilot.pause(0.2)
        assert screen._current_step == STEPS.index("step-done")


async def test_wizard_viz_llm_run_uses_prefetch_mock(tmp_path: Path) -> None:
    from brainkm.services.webllm_prefetch import PrefetchResult

    app = BrainkmConfigureApp(project_dir=tmp_path)
    async with app.run_test(size=(140, 70)) as pilot:
        await pilot.pause(0.3)
        (tmp_path / ".brain").mkdir(exist_ok=True)
        (tmp_path / ".brain" / "config.json").write_text("{}", encoding="utf-8")

        screen = app.screen
        screen._current_step = STEPS.index(STEP_VIZ_LLM)
        screen._update_step_visibility()
        await pilot.pause(0.1)

        fake = PrefetchResult(
            model_id="Llama-3.2-1B-Instruct-q4f16_1-MLC",
            cache_dir=tmp_path / "cache",
            files_downloaded=3,
            files_skipped=0,
            bytes_downloaded=1024 * 1024,
            already_cached=False,
        )
        with patch(
            "brainkm.services.webllm_prefetch.prefetch_webllm_model",
            return_value=fake,
        ):
            await pilot.click("#btn-wizard-run")
            await pilot.pause(1.5)

        cfg = json.loads((tmp_path / ".brain" / "config.json").read_text())
        assert cfg["viz"]["webllm_model"] == "Llama-3.2-1B-Instruct-q4f16_1-MLC"
        assert screen._current_step == STEPS.index("step-done")