"""SVG snapshot regression tests for the configure TUI (dark theme)."""

from __future__ import annotations

from pathlib import Path

import pytest

from brainkm.tui.app import BrainkmConfigureApp


@pytest.fixture(autouse=True)
def _stable_tui_log_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAINKM_TUI_FIXED_TIME", "12:00:00")


async def _pause(pilot) -> None:
    await pilot.pause()


def test_snapshot_dashboard(snap_compare, tui_project: Path) -> None:
    async def go(pilot) -> None:
        await pilot.pause()
        pilot.app.sub_title = "/tmp/brainkm-tui-snapshot"
        await pilot.pause()

    assert snap_compare(
        BrainkmConfigureApp(project_dir=tui_project),
        terminal_size=(100, 36),
        run_before=go,
    )


def test_snapshot_config(snap_compare, tui_project: Path) -> None:
    async def go(pilot) -> None:
        await pilot.pause()
        pilot.app.sub_title = "/tmp/brainkm-tui-snapshot"
        await pilot.press("c")
        await pilot.pause()

    assert snap_compare(
        BrainkmConfigureApp(project_dir=tui_project),
        terminal_size=(100, 36),
        run_before=go,
    )


def test_snapshot_actions(snap_compare, tui_project: Path) -> None:
    async def go(pilot) -> None:
        await pilot.pause()
        pilot.app.sub_title = "/tmp/brainkm-tui-snapshot"
        await pilot.press("a")
        await pilot.pause()

    assert snap_compare(
        BrainkmConfigureApp(project_dir=tui_project),
        terminal_size=(100, 36),
        run_before=go,
    )


def test_snapshot_wizard(snap_compare, tmp_path: Path) -> None:
    # Use a stable absolute path so the SVG baseline doesn't embed pytest tmp dirs.
    project = Path("/tmp/brainkm-wizard-snapshot")
    if project.exists():
        import shutil

        shutil.rmtree(project)
    project.mkdir(parents=True)

    async def go(pilot) -> None:
        await pilot.pause()

    assert snap_compare(
        BrainkmConfigureApp(project_dir=project),
        terminal_size=(100, 36),
        run_before=go,
    )
