"""Tests for the Dashboard screen (Cyber-Industrial layout)."""

from __future__ import annotations

import json
from pathlib import Path

from textual.containers import VerticalScroll
from textual.widgets import Button

from brainkm.db.connection import connect
from brainkm.tui.app import BrainkmConfigureApp
from brainkm.tui.widgets.review_table import ReviewTable
from brainkm.tui.widgets.status_panel import StatusPanel


async def test_dashboard_brands_via_header_and_scrolls(tui_project: Path) -> None:
    """Brand lives in the Header; dashboard body scrolls instead of clipping."""
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause(0.3)
        assert app.title == "BrainKm"
        assert not app.screen.query("#brand-banner")
        assert isinstance(app.screen.query_one("#dashboard-container"), VerticalScroll)


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
        assert "distill" in labels
        assert "neurons" in labels
        assert "edges" in labels
        assert "observe" in labels
        assert "mcp" in labels
        assert "model" not in labels
        distill_row = next(item for item in panel._items if item[0] == "distill")
        # Readiness-aware display: mode + detail in parentheses
        assert "(" in distill_row[1], f"expected readiness suffix, got {distill_row[1]!r}"


async def test_dashboard_serve_panel_shows_mismatch_and_restart_button(
    tui_project: Path,
) -> None:
    """Stale HTTP serve enables Restart and surfaces package vs serve versions."""
    from brainkm.models.brain_config import BrainConfig, McpConfig
    from brainkm.services.config_loader import save_brain_config

    save_brain_config(
        tui_project,
        BrainConfig(mcp=McpConfig(transport="http", http_port=18769)),
    )
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(140, 60)) as pilot:
        await pilot.pause(0.3)
        restart = app.screen.query_one("#btn-restart-serve", Button)
        start = app.screen.query_one("#btn-start-serve", Button)
        app.screen._render_serve_status(
            {
                "running": True,
                "transport": "http",
                "url": "http://127.0.0.1:18769/health",
                "port": 18769,
                "detail": '{"ok":true,"version":"0.0.1"}',
                "serve_version": "0.0.1",
                "package_version": "0.8.6",
                "version_mismatch": True,
            }
        )
        await pilot.pause(0.1)
        panel = app.screen.query_one("#serve-status", StatusPanel)
        labels = [item[0] for item in panel._items]
        assert "Package" in labels
        assert "Port" in labels
        assert "Serve" not in labels
        assert "URL" not in labels
        assert "Observe" not in labels
        assert any(item[0] == "Fix" and "Restart" in item[1] for item in panel._items)
        assert restart.disabled is False
        assert start.disabled is False  # Start also force-restarts when stale
        # Labels must be visible (height:1 + border:tall blanks them).
        assert "Start" in str(start.label)
        assert "Restart" in str(restart.label)
        stop = app.screen.query_one("#btn-stop-serve", Button)
        assert "Stop" in str(stop.label)

    """Groq doctor must show the config model (accent) and surface 429 in red."""
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(140, 60)) as pilot:
        await pilot.pause(0.3)
        app.screen._render_groq_status(
            {
                "api_key_present": True,
                "api_key_masked": "gsk_...test",
                "reachable": True,
                "config_model": "llama-3.3-70b-versatile",
                "error": None,
                "rate_limited": False,
            }
        )
        await pilot.pause(0.2)

        panel = app.screen.query_one("#groq-panel", StatusPanel)
        model_row = next(item for item in panel._items if item[0] == "Model")
        assert model_row[1] == "llama-3.3-70b-versatile"
        assert model_row[2] == "accent"

        app.screen._render_groq_status(
            {
                "api_key_present": True,
                "api_key_masked": "gsk_...test",
                "reachable": False,
                "config_model": "llama-3.3-70b-versatile",
                "error": "rate limited (429); retry-after 3s",
                "rate_limited": True,
            }
        )
        await pilot.pause(0.2)

        assert any(item[1] == "RATE LIMITED" and item[2] == "error" for item in panel._items)
        model_row = next(item for item in panel._items if item[0] == "Model")
        assert model_row[1] == "llama-3.3-70b-versatile"
        banner = app.screen.query_one("#rate-limit-banner")
        assert "visible" in banner.classes
        sidebar = app.screen.query_one("#brain-status", StatusPanel)
        assert any(item[0] == "Groq" and "RATE LIMITED" in item[1] for item in sidebar._items)


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


async def test_dashboard_mcp_doctor_panel_and_empty_review_hint(
    tui_project: Path,
    monkeypatch,
) -> None:
    """MCP Doctor fills on refresh; empty Review Queue explains approve/reject."""
    from brainkm.services.mcp_doctor import ClientWireStatus, McpDoctorReport

    fake = McpDoctorReport(
        project_dir=tui_project,
        health_ok=True,
        health_url="http://127.0.0.1:8765/health",
        health_detail="ok",
        config_transport="stdio",
        auto_observe=False,
        clients=[
            ClientWireStatus(
                client="cursor",
                mcp_path=tui_project / ".cursor" / "mcp.json",
                present=True,
                transport="stdio",
                hooks_present=True,
            )
        ],
    )
    monkeypatch.setattr(
        "brainkm.services.mcp_doctor.build_mcp_doctor_report",
        lambda *_a, **_k: fake,
    )

    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(140, 60)) as pilot:
        await pilot.pause(0.8)
        panel = app.screen.query_one("#mcp-doctor-panel", StatusPanel)
        assert panel._items, "mcp-doctor-panel should populate after mount"
        labels = [item[0] for item in panel._items]
        assert "Overall" in labels
        assert "Transport" in labels
        assert any(item[2] in ("ok", "warning", "error", "muted") for item in panel._items)

        hint = app.screen.query_one("#review-hint")
        hint_text = str(hint.render())
        assert "approve" in hint_text.lower()
        section = app.screen.query_one("#review-section")
        assert "review-section--empty" in section.classes


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


async def test_dashboard_worker_error_renders_panel_error(tui_project: Path) -> None:
    """Worker ERROR must toast and paint an error state — not leave panels stuck."""
    from textual.worker import WorkerState

    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(140, 60)) as pilot:
        await pilot.pause(0.5)
        screen = app.screen

        class _FakeWorker:
            group = "ollama-status"
            error = RuntimeError("probe boom")
            result = None

        class _FakeEvent:
            state = WorkerState.ERROR
            worker = _FakeWorker()

        screen._on_worker_state_changed(_FakeEvent())  # type: ignore[arg-type]
        await pilot.pause(0.3)

        panel = screen.query_one("#ollama-panel", StatusPanel)
        assert any(item[2] == "error" for item in panel._items)
        assert any("probe boom" in item[1] for item in panel._items)


async def test_review_empty_state_uses_static_not_datatable_row(
    tui_project: Path,
) -> None:
    """Empty review queue must not paint a purple selected DataTable row."""
    from textual.widgets import Static

    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(140, 60)) as pilot:
        await pilot.pause(0.6)
        table = app.screen.query_one("#review-table", ReviewTable)
        empty = table.query_one("#review-empty", Static)
        assert empty.display is True
        assert table.table.display is False
        assert table.get_selected_node_id() is None


async def test_status_panel_rapid_refresh_does_not_duplicate_rows(
    tui_project: Path,
) -> None:
    """Rapid set_items must keep the last snapshot (single body Static render)."""
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(140, 60)) as pilot:
        await pilot.pause(0.4)
        panel = app.screen.query_one("#brain-status", StatusPanel)
        for i in range(5):
            panel.set_items(
                [
                    ("distill", f"mode-{i}", "muted"),
                    ("neurons", str(i), "ok"),
                ]
            )
        await pilot.pause(0.2)
        assert len(panel._items) == 2
        assert panel._items[0][1] == "mode-4"
        body = panel.query_one("#brain-status-body")
        rendered = str(body.render())
        assert "mode-4" in rendered
        assert "mode-0" not in rendered
