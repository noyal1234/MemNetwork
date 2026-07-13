"""Tests for the Dashboard screen (Cyber-Industrial layout)."""

from __future__ import annotations

import json
from pathlib import Path

from textual.widgets import Button

from brainkm.db.connection import connect
from brainkm.tui.app import BrainkmConfigureApp
from brainkm.tui.widgets.review_table import ReviewTable
from brainkm.tui.widgets.status_panel import StatusPanel


def _seed_pending_review_item(
    project_dir: Path, node_id: str = "01J7TESTNODE0000000000000"
) -> None:
    """Insert a node row + matching pending/*.json file, as review.py expects."""
    from datetime import UTC, datetime

    db_path = project_dir / ".brain" / "brain.db"
    conn = connect(db_path)
    try:
        now = datetime.now(UTC).isoformat()
        conn.execute(
            """
            INSERT INTO nodes (
              id, kind, subtype, title, content, confidence, ingested_at, created_at, updated_at
            ) VALUES (?, 'memory', 'decision', ?, 'test content', 0.4, ?, ?, ?)
            """,
            (node_id, "Test decision needing review", now, now, now),
        )
        conn.commit()
    finally:
        conn.close()

    pending_dir = project_dir / ".brain" / "pending"
    pending_dir.mkdir(parents=True, exist_ok=True)
    (pending_dir / f"{node_id}.json").write_text(
        json.dumps(
            {
                "node_id": node_id,
                "title": "Test decision needing review",
                "subtype": "decision",
                "confidence": 0.4,
            }
        ),
        encoding="utf-8",
    )


async def test_dashboard_loads_brain_status(tui_project: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test() as pilot:
        await pilot.pause(0.5)
        panel = app.screen.query_one("#brain-status", StatusPanel)
        assert panel._items, "brain-status panel should be populated after mount"
        labels = [item[0] for item in panel._items]
        assert "distill_mode" in labels
        assert "neurons" in labels


async def test_dashboard_sidebar_includes_channel_rows(tui_project: Path) -> None:
    """Channels are folded into #brain-status (no separate #channel-status)."""
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(140, 60)) as pilot:
        await pilot.pause(1.0)
        panel = app.screen.query_one("#brain-status", StatusPanel)
        assert panel._items, "brain-status sidebar should be populated"
        labels = {item[0] for item in panel._items}
        assert "Ollama" in labels
        assert "Groq" in labels
        assert not app.screen.query("#channel-status")


async def test_dashboard_action_buttons_exist(tui_project: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(140, 60)) as pilot:
        await pilot.pause(0.3)
        for btn_id in (
            "btn-ollama-apply",
            "btn-groq-refresh",
            "btn-graph-sync",
            "btn-graph-extract",
            "btn-graph-status",
        ):
            assert app.screen.query_one(f"#{btn_id}", Button) is not None


async def test_dashboard_graph_status_button_does_not_crash(tui_project: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(160, 80)) as pilot:
        await pilot.pause(0.5)
        # Invoke handler directly — graph action row may be below fold in small terms
        app.screen._run_graph_status_action()
        await pilot.pause(0.8)
        panel = app.screen.query_one("#graph-panel", StatusPanel)
        assert panel._items is not None


async def test_dashboard_groq_refresh_does_not_crash(tui_project: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(160, 80)) as pilot:
        await pilot.pause(0.5)
        app.screen._run_groq_refresh()
        await pilot.pause(0.8)
        assert app.screen is not None


async def test_dashboard_graph_sync_and_extract_do_not_crash(tui_project: Path) -> None:
    """Buttons may fail (no graphify) but must not crash the screen."""
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(160, 80)) as pilot:
        await pilot.pause(0.5)
        app.screen._run_graph_extract()
        await pilot.pause(0.8)
        app.screen._run_graph_sync()
        await pilot.pause(1.0)
        assert app.screen is not None


async def test_dashboard_review_table_empty_state(tui_project: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test() as pilot:
        await pilot.pause(0.5)
        table = app.screen.query_one("#review-table", ReviewTable)
        # Fresh brain has no pending review items.
        assert table.get_selected_node_id() is None


async def test_dashboard_refresh_does_not_crash(tui_project: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test() as pilot:
        await pilot.pause(0.3)
        await pilot.press("r")
        await pilot.pause(0.5)
        assert app.screen is not None


async def test_dashboard_status_panel_renders_without_markup_tags(tui_project: Path) -> None:
    """Status values must use CSS classes, not raw [value--ok] markup tags."""
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        panel = app.screen.query_one("#brain-status", StatusPanel)
        for widget in panel.query("Static"):
            text = str(widget.render())
            assert "[value--" not in text


async def test_review_queue_approve_flow(tui_project: Path) -> None:
    node_id = "01J7TESTNODE0000000000001"
    _seed_pending_review_item(tui_project, node_id)

    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(140, 60)) as pilot:
        await pilot.pause(0.8)
        table = app.screen.query_one("#review-table", ReviewTable)
        assert table.get_selected_node_id() == node_id

        await pilot.press("y")
        await pilot.pause(0.8)

        pending_path = tui_project / ".brain" / "pending" / f"{node_id}.json"
        assert not pending_path.exists()


async def test_review_queue_reject_flow(tui_project: Path) -> None:
    node_id = "01J7TESTNODE0000000000002"
    _seed_pending_review_item(tui_project, node_id)

    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(140, 60)) as pilot:
        await pilot.pause(0.8)
        table = app.screen.query_one("#review-table", ReviewTable)
        assert table.get_selected_node_id() == node_id

        await pilot.press("n")
        await pilot.pause(0.8)

        pending_path = tui_project / ".brain" / "pending" / f"{node_id}.json"
        assert not pending_path.exists()
