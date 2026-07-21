"""Modal showing full pending-review neuron detail (Enter from Review Queue)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from brainkm.tui.theme import bracket_label, escape_markup

ReviewDetailAction = Literal["approve", "reject"]


def load_review_detail(
    node_id: str,
    *,
    project_dir: Path | None = None,
    title: str = "",
    subtype: str = "",
    confidence: float = 0.0,
) -> dict[str, str]:
    """Load full neuron fields for the review detail modal."""
    detail: dict[str, str] = {
        "node_id": node_id,
        "title": title or "(no title)",
        "subtype": subtype or "—",
        "confidence": f"{confidence:.2f}",
        "body": "(body unavailable)",
        "source": "—",
        "path": "—",
    }
    try:
        from brainkm.db.connection import connect
        from brainkm.db.paths import brain_db_path
        from brainkm.services.memory import get_node

        conn = connect(brain_db_path(project_dir))
        try:
            record = get_node(conn, node_id)
            if record is None:
                detail["body"] = "(neuron not found in brain.db)"
                return detail
            detail["title"] = record.title or detail["title"]
            detail["subtype"] = record.subtype or detail["subtype"]
            detail["body"] = (record.content or "").strip() or "(empty body)"
            row = conn.execute(
                "SELECT confidence, source, path FROM nodes WHERE id = ?",
                (node_id,),
            ).fetchone()
            if row is not None:
                detail["confidence"] = f"{float(row['confidence']):.2f}"
                if row["source"]:
                    detail["source"] = str(row["source"])
                if row["path"]:
                    detail["path"] = str(row["path"])
        finally:
            conn.close()
    except Exception as exc:
        detail["body"] = f"(failed to load body: {exc})"
    return detail


class ReviewDetailModal(ModalScreen[ReviewDetailAction | None]):
    """Show full review item; return approve / reject / None (close)."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("y", "approve", "Approve"),
        ("n", "reject", "Reject"),
    ]

    def __init__(
        self,
        *,
        node_id: str,
        project_dir: Path | None = None,
        title: str = "",
        subtype: str = "",
        confidence: float = 0.0,
    ) -> None:
        super().__init__()
        self._detail = load_review_detail(
            node_id,
            project_dir=project_dir,
            title=title,
            subtype=subtype,
            confidence=confidence,
        )

    def compose(self) -> ComposeResult:
        d = self._detail
        with Vertical(id="review-detail-box"):
            yield Static(
                escape_markup("Review detail"),
                classes="modal-title",
            )
            yield Static(
                escape_markup(
                    f"ID: {d['node_id']}\n"
                    f"Subtype: {d['subtype']}    Confidence: {d['confidence']}\n"
                    f"Source: {d['source']}    Path: {d['path']}"
                ),
                classes="modal-meta",
            )
            yield Static(
                escape_markup(f"Title: {d['title']}"),
                classes="modal-title-line",
            )
            with VerticalScroll(id="review-detail-body-scroll"):
                yield Static(
                    escape_markup(d["body"]),
                    id="review-detail-body",
                    classes="modal-body",
                )
            yield Static(
                escape_markup("y approve · n reject · Esc close"),
                classes="modal-hint",
            )
            with Horizontal(classes="modal-buttons"):
                yield Button(bracket_label("Close"), id="btn-review-close")
                yield Button(
                    bracket_label("Reject"),
                    id="btn-review-reject",
                    classes="-error",
                )
                yield Button(
                    bracket_label("Approve"),
                    id="btn-review-approve",
                    classes="-primary",
                )

    def action_close(self) -> None:
        self.dismiss(None)

    def action_approve(self) -> None:
        self.dismiss("approve")

    def action_reject(self) -> None:
        self.dismiss("reject")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-review-approve":
            self.dismiss("approve")
        elif event.button.id == "btn-review-reject":
            self.dismiss("reject")
        else:
            self.dismiss(None)
