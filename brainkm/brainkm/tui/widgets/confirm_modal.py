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
    """

    DEFAULT_CSS = """
    ConfirmDiscardModal {
        align: center middle;
    }

    ConfirmDiscardModal > Vertical {
        width: 56;
        height: auto;
        border: solid $primary-container;
        background: $surface-alt;
        padding: 1 2;
    }

    ConfirmDiscardModal .modal-title {
        text-style: bold;
        color: $warning;
        height: 1;
        margin-bottom: 1;
    }

    ConfirmDiscardModal .modal-body {
        color: $text;
        height: auto;
        margin-bottom: 1;
    }

    ConfirmDiscardModal .modal-buttons {
        layout: horizontal;
        height: 3;
        align: right middle;
    }

    ConfirmDiscardModal .modal-buttons Button {
        margin: 0 0 0 1;
        min-width: 12;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
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
                    id="btn-discard",
                    classes="-error",
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-discard":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def on_key(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.key == "escape":
            self.dismiss(False)
