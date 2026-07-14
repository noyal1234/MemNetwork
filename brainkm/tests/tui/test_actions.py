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
        "btn-cursor-doctor",
        "btn-export",
        "btn-repair",
        "btn-bench-token",
        "btn-viz-demo",
    ],
)
async def test_action_button_does_not_crash(tui_project: Path, button_id: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("webbrowser.open", lambda *_a, **_k: True)
    monkeypatch.setattr(
        "brainkm.services.graphify_sync.sync_graph",
        lambda **_kwargs: type(
            "R",
            (),
            {
                "status": "skipped",
                "message": "mocked",
                "import_result": None,
            },
        )(),
    )
    monkeypatch.setattr(
        "brainkm.services.bench_runner.run_bench_suite",
        lambda suite, db_path: type(
            "B",
            (),
            {"suite": suite, "passed": 1, "total": 1, "cases": []},
        )(),
    )
    monkeypatch.setattr(
        "brainkm.services.repair.repair_brain",
        lambda **_kwargs: type(
            "Rep",
            (),
            {"fts_rows_rebuilt": 0, "integrity_ok": True, "secrets_archived": 0},
        )(),
    )
    monkeypatch.setattr(
        "brainkm.services.viz.start_viz_server",
        lambda **_kwargs: type(
            "H",
            (),
            {
                "url": "http://127.0.0.1:5757/",
                "port": 5757,
                "thread": type("T", (), {"is_alive": lambda self: True})(),
                "stop": lambda self: None,
            },
        )(),
    )

    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(140, 60)) as pilot:
        app.switch_screen("actions")
        await pilot.pause(0.3)
        await pilot.click(f"#{button_id}")
        await pilot.pause(0.5)
        assert app.screen is not None
        handle = getattr(app.screen, "_viz_handle", None)
        if handle is not None:
            handle.stop()
            app.screen._viz_handle = None


async def test_viz_demo_writes_url_to_log(tui_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("webbrowser.open", lambda *_a, **_k: True)
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(140, 60)) as pilot:
        app.switch_screen("actions")
        await pilot.pause(0.3)
        await pilot.click("#btn-viz-demo")
        await pilot.pause(2.0)
        log = app.screen.query_one("#action-log", RichLogPanel)
        text = " ".join(str(line) for line in log.rich_log.lines)
        assert "http://127.0.0.1:" in text or "Viz" in text
        handle = app.screen._viz_handle
        if handle is not None:
            handle.stop()


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
