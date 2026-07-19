"""Confirm / discard modal used when leaving a dirty Config editor."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from brainkm.tui.theme import bracket_label, escape_markup


class ConfirmDiscardModal(ModalScreen[bool]):
    """Ask whether to discard unsaved config changes.

    Returns ``True`` if the user chooses Discard, ``False`` for Cancel.
    Styles live in ``styles/app.tcss`` (``ConfirmDiscardModal`` rules) so
    custom design tokens resolve correctly.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-discard-box"):
            yield Static(
                escape_markup("Unsaved changes"),
                classes="modal-title",
            )
            yield Static(
                "You have unsaved config edits. Discard them and leave?",
                classes="modal-body",
            )
            with Horizontal(classes="modal-buttons"):
                yield Button(bracket_label("Cancel"), id="btn-cancel")
                yield Button(
                    bracket_label("Discard"),
                    id="btn-discard-confirm",
                    classes="-error",
                )

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-discard-confirm":
            self.dismiss(True)
        else:
            self.dismiss(False)
