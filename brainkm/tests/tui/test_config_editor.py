"""Tests for the Config Editor screen — load, edit, validate, save."""

from __future__ import annotations

import json
from pathlib import Path

from textual.widgets import Button, Input, Switch

from brainkm.tui.app import BrainkmConfigureApp
from brainkm.tui.widgets.config_form import SECTION_FIELDS, ConfigForm


async def test_loading_config_does_not_mark_it_dirty(tui_project: Path) -> None:
    """Regression test: mounting Select/Switch widgets with their initial
    value fires a Textual `Changed` event even without user interaction.
    Opening the Config Editor must not immediately enable Save.
    """
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(120, 60)) as pilot:
        app.switch_screen("config")
        await pilot.pause(0.6)
        screen = app.screen
        assert screen._dirty is False
        assert screen.query_one("#btn-save", Button).disabled is True


async def test_editing_a_field_enables_save(tui_project: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(120, 60)) as pilot:
        app.switch_screen("config")
        await pilot.pause(0.6)
        screen = app.screen

        switch = screen.query_one("#field-ollama-auto_select_model", Switch)
        switch.toggle()
        await pilot.pause(0.3)

        assert screen._dirty is True
        assert screen.query_one("#btn-save", Button).disabled is False


async def test_save_writes_edited_value_to_the_right_project(tui_project: Path) -> None:
    """Regression test: saving must write to *this* project's config.json,
    not to cwd's `.brain/config.json` (see test_app.py project_dir binding
    regression test for the root cause this guards against).
    """
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(120, 60)) as pilot:
        app.switch_screen("config")
        await pilot.pause(0.6)
        screen = app.screen

        switch = screen.query_one("#field-ollama-auto_select_model", Switch)
        assert switch.value is False  # default
        switch.toggle()
        await pilot.pause(0.3)

        screen._save_config()
        await pilot.pause(0.2)

        cfg_path = tui_project / ".brain" / "config.json"
        saved = json.loads(cfg_path.read_text())
        assert saved["ollama"]["auto_select_model"] is True
        assert screen._dirty is False
        assert screen.query_one("#btn-save", Button).disabled is True


async def test_invalid_value_disables_save_and_shows_error(tui_project: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(120, 60)) as pilot:
        app.switch_screen("config")
        await pilot.pause(0.6)
        screen = app.screen

        field = screen.query_one("#field-budget-total_tokens", Input)
        field.value = "999999"  # exceeds BudgetConfig.total_tokens le=8000
        await pilot.pause(0.3)

        assert screen._validation_error is not None
        assert screen.query_one("#btn-save", Button).disabled is True


async def test_groq_api_key_written_to_env_not_config(tui_project: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(120, 60)) as pilot:
        app.switch_screen("config")
        await pilot.pause(0.6)
        screen = app.screen

        key_input = screen.query_one("#field-groq-api-key", Input)
        key_input.value = "gsk_test_secret_value"
        await pilot.pause(0.1)

        screen._save_config()
        await pilot.pause(0.2)

        env_path = tui_project / ".env"
        assert env_path.is_file()
        assert "GROQ_API_KEY=gsk_test_secret_value" in env_path.read_text()

        cfg_path = tui_project / ".brain" / "config.json"
        saved_text = cfg_path.read_text()
        assert "gsk_test_secret_value" not in saved_text


async def test_discard_reload_does_not_duplicate_form_ids(tui_project: Path) -> None:
    """Regression test: Textual 8 remove_children()/mount() are async; reloading
    config (Discard, or revisiting the screen) without awaiting removal raised
    DuplicateIds for form-capture.
    """
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(120, 60)) as pilot:
        app.switch_screen("config")
        await pilot.pause(0.6)

        await pilot.click("#btn-discard")
        await pilot.pause(0.6)

        app.switch_screen("dashboard")
        await pilot.pause(0.2)
        app.switch_screen("config")
        await pilot.pause(0.6)

        screen = app.screen
        forms = screen.query("#config-forms ConfigForm")
        ids = [form.id for form in forms]
        assert len(ids) == len(set(ids)), f"duplicate form ids: {ids}"


async def test_distill_status_line_renders(tui_project: Path) -> None:
    from textual.widgets import Static

    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(120, 60)) as pilot:
        app.switch_screen("config")
        await pilot.pause(0.8)
        screen = app.screen
        line = screen.query_one("#distill-status-line", Static)
        assert line is not None
        # Drive the apply path synchronously (worker may still be probing).
        screen._apply_distill_status(
            {
                "line": (
                    "Distill readiness: cursor heuristic active (no agent CLI) "
                    "| ollama unreachable | groq unreachable"
                )
            }
        )
        await pilot.pause(0.1)
        # Widget still addressable after update; content lives in Textual internals.
        assert screen.query_one("#distill-status-line", Static) is line


async def test_all_config_sections_sized_in_compact_terminal(tui_project: Path) -> None:
    """Regression: at ~120x30, #config-forms must grow with content so Ollama
    and later sections are scrollable — not clipped inside a 1fr Vertical.
    """
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(120, 30)) as pilot:
        app.switch_screen("config")
        # Config forms mount after an async load worker; wait until sized.
        capture = None
        for _ in range(40):
            await pilot.pause(0.1)
            try:
                capture = app.screen.query_one("#form-capture", ConfigForm)
            except Exception:
                continue
            if capture.size.height >= 5:
                break
        assert capture is not None and capture.size.height >= 5

        screen = app.screen
        forms = list(screen.query(ConfigForm))
        assert len(forms) == len(SECTION_FIELDS)

        ollama = screen.query_one("#form-ollama", ConfigForm)
        # Ollama must be stacked below Capture with real field height.
        assert ollama.size.height >= 5
        assert ollama.region.y > capture.region.y

        forms_container = screen.query_one("#config-forms")
        scroll = screen.query_one("#config-container")
        # Content taller than the viewport ⇒ VerticalScroll can reveal Ollama+.
        assert forms_container.virtual_size.height > scroll.size.height
