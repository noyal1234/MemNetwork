"""Tests for Review Queue detail modal."""

from __future__ import annotations

from pathlib import Path

from brainkm.tui.app import BrainkmConfigureApp
from brainkm.tui.widgets.review_detail_modal import (
    ReviewDetailModal,
    load_review_detail,
)
from brainkm.tui.widgets.review_table import ReviewTable
from tests.tui.test_dashboard import _seed_pending_review_item


def test_load_review_detail_includes_body(tui_project: Path) -> None:
    node_id = "01J7DETAIL0000000000001"
    _seed_pending_review_item(tui_project, node_id)
    detail = load_review_detail(
        node_id,
        project_dir=tui_project,
        title="fallback",
        subtype="decision",
        confidence=0.4,
    )
    assert detail["node_id"] == node_id
    assert "Test decision" in detail["title"]
    assert detail["body"] == "test content"
    assert detail["confidence"] == "0.40"


async def test_enter_opens_review_detail_modal(tui_project: Path) -> None:
    node_id = "01J7DETAIL0000000000002"
    _seed_pending_review_item(tui_project, node_id)
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(140, 50)) as pilot:
        await pilot.pause(0.8)
        table = app.screen.query_one("#review-table", ReviewTable)
        assert table.get_selected_node_id() == node_id
        await pilot.press("enter")
        await pilot.pause(0.4)
        assert any(isinstance(s, ReviewDetailModal) for s in app.screen_stack)
        body = app.screen.query_one("#review-detail-body")
        assert "test content" in str(body.render())
        await pilot.press("escape")
        await pilot.pause(0.3)
        assert not any(isinstance(s, ReviewDetailModal) for s in app.screen_stack)


async def test_review_detail_approve_from_modal(tui_project: Path) -> None:
    node_id = "01J7DETAIL0000000000003"
    _seed_pending_review_item(tui_project, node_id)
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(140, 50)) as pilot:
        await pilot.pause(0.8)
        await pilot.press("enter")
        await pilot.pause(0.4)
        assert any(isinstance(s, ReviewDetailModal) for s in app.screen_stack)
        await pilot.press("y")
        await pilot.pause(1.0)
        pending = tui_project / ".brain" / "pending" / f"{node_id}.json"
        assert not pending.exists()
