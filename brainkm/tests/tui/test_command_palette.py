from __future__ import annotations

from pathlib import Path

from textual.command import CommandPalette

from brainkm.tui.app import BrainkmConfigureApp
from brainkm.tui.screens.config_editor import ConfigEditorScreen
from brainkm.tui.widgets.command_palette import (
    _COMMAND_TO_SCREEN,
    BrainkmCommandProvider,
    enumerate_cli_commands,
)


def test_enumerate_cli_commands_finds_grouped_and_flat_commands() -> None:
    """Regression test: Typer vendors its own Click fork
    (`typer._click.core.Command`), so a naive `isinstance(cmd, click.Group)`
    check (as sketched in the original plan doc) silently fails to recurse
    into sub-groups like `graph`/`bench`/`review`/`ollama`/`groq`. This must
    use duck-typing (`hasattr(cmd, "commands")`) instead.
    """
    commands = enumerate_cli_commands()
    names = {c["name"] for c in commands}

    assert "version" in names
    assert "configure" in names
    # Sub-group commands must be discovered too, not just the group name.
    assert "graph sync" in names
    assert "graph status" in names
    assert "bench run" in names
    assert "review approve" in names
    assert "ollama doctor" in names
    assert "groq doctor" in names
    # Group names themselves are never leaf commands.
    assert "graph" not in names
    assert "bench" not in names


async def test_command_palette_opens_on_slash(tui_project: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(130, 55)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("slash")
        await pilot.pause(0.3)
        assert any(isinstance(s, CommandPalette) for s in app.screen_stack)
        await pilot.press("escape")


async def test_command_palette_registers_brainkm_provider(tui_project: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tui_project)
    assert BrainkmCommandProvider in app.COMMANDS


async def test_command_palette_navigation_hit_switches_screen(tui_project: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(130, 55)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("slash")
        await pilot.pause(0.3)

        for char in "Config Editor":
            await pilot.press(*([char] if char != " " else ["space"]))
        await pilot.pause(0.3)
        await pilot.press("enter")
        await pilot.pause(0.5)

        assert isinstance(app.screen, ConfigEditorScreen)


def test_review_cli_commands_route_to_dashboard() -> None:
    """Review queue lives on the Dashboard, not Actions."""
    assert _COMMAND_TO_SCREEN["review list"] == "dashboard"
    assert _COMMAND_TO_SCREEN["review approve"] == "dashboard"
    assert _COMMAND_TO_SCREEN["review reject"] == "dashboard"
