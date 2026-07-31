"""Uninstall modal — pick which clients to unwire and whether to purge .brain/."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Static

from brainkm.tui.theme import bracket_label, escape_markup
from brainkm.tui.widgets.app_pick import AppPickCheckbox

UNINSTALL_APPS: list[tuple[str, str, str]] = [
    ("cursor", "uninstall-app-cursor", "Cursor"),
    ("claude", "uninstall-app-claude", "Claude Code"),
    ("antigravity", "uninstall-app-antigravity", "Antigravity"),
    ("codex", "uninstall-app-codex", "Codex"),
]


@dataclass(frozen=True)
class UninstallChoice:
    """What the user confirmed in the modal."""

    clients: list[str]
    purge: bool


class UninstallModal(ModalScreen[UninstallChoice | None]):
    """Confirm removal of brainkm wiring.

    Dismisses with an :class:`UninstallChoice`, or ``None`` on cancel. Clients
    already wired in the project are pre-checked; ``.brain/`` is kept unless the
    purge box is ticked, since project memory is user data.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, *, project_dir: Path | None = None, wired: list[str] | None = None) -> None:
        super().__init__()
        self._project_dir = project_dir
        self._wired = wired if wired is not None else []

    def compose(self) -> ComposeResult:
        with Vertical(id="uninstall-box"):
            yield Static(escape_markup("[ UNINSTALL BRAINKM ]"), classes="modal-title")
            yield Static(
                "Removes the brainkm MCP entry, hooks, routing rules and skills "
                "from the apps below. Other entries in those files are preserved.",
                classes="modal-body",
            )
            with Vertical(id="uninstall-app-list"):
                for kind, widget_id, label in UNINSTALL_APPS:
                    suffix = "  (wired)" if kind in self._wired else ""
                    yield AppPickCheckbox(
                        f"{label}{suffix}",
                        id=widget_id,
                        value=kind in self._wired,
                    )
            yield Checkbox(
                "Also delete .brain/ — project memory, irreversible",
                id="uninstall-purge",
                value=False,
            )
            yield Static(
                "Git hooks and a running shared brain are cleaned up once no app is left wired.",
                classes="modal-hint",
            )
            with Horizontal(classes="modal-buttons"):
                yield Button(bracket_label("Cancel"), id="btn-uninstall-cancel")
                yield Button(
                    bracket_label("Uninstall"),
                    id="btn-uninstall-confirm",
                    classes="-error",
                )

    def selected_clients(self) -> list[str]:
        selected: list[str] = []
        for kind, widget_id, _label in UNINSTALL_APPS:
            try:
                if self.query_one(f"#{widget_id}", AppPickCheckbox).value:
                    selected.append(kind)
            except Exception:
                continue
        return selected

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "btn-uninstall-confirm":
            self.dismiss(None)
            return
        clients = self.selected_clients()
        if not clients:
            self.notify("Select at least one app to uninstall.", severity="warning", timeout=5)
            return
        purge = self.query_one("#uninstall-purge", Checkbox).value
        self.dismiss(UninstallChoice(clients=clients, purge=bool(purge)))
