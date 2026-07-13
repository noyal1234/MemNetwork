"""Reusable status card widget — icon + label + value with colored state."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static


class StatusPanel(Static):
    """A bordered card showing key/value rows with a colored status dot.

    Usage::

        panel = StatusPanel(title="Ollama", id="ollama-panel")
        panel.set_items([
            ("Status", "reachable", "ok"),
            ("Model", "qwen2.5:3b", "muted"),
            ("Tier", "standard", "muted"),
        ])
    """

    DEFAULT_CSS = """
    StatusPanel {
        height: auto;
    }

    StatusPanel .status-row {
        height: 1;
        margin: 0 0 0 0;
    }

    StatusPanel .status-label {
        width: 18;
        color: $text-muted;
    }

    StatusPanel .status-value {
        width: 1fr;
    }
    """

    def __init__(
        self,
        title: str = "",
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=f"status-panel {classes or ''}")
        self._title = title
        self._items: list[tuple[str, str, str]] = []

    def compose(self) -> ComposeResult:
        yield Static(self._title, classes="panel-title")
        yield Vertical(id=f"{self.id}-body" if self.id else "panel-body")

    def set_items(self, items: list[tuple[str, str, str]]) -> None:
        """Set the panel content.

        Args:
            items: List of (label, value, state) tuples.
                   state is one of: "ok", "warning", "error", "muted".
        """
        self._items = items
        self._render_items()

    def _render_items(self) -> None:
        body_id = f"#{self.id}-body" if self.id else "#panel-body"
        try:
            body = self.query_one(body_id)
        except Exception:
            return
        body.remove_children()
        for label, value, state in self._items:
            dot = self._state_dot(state)
            row = Horizontal(classes="status-row")
            body.mount(row)
            row.mount(
                Static(f"  {label}:", classes="status-label"),
                Static(f"{dot} {value}", classes=f"status-value value--{state}"),
            )

    def _state_dot(self, state: str) -> str:
        return {"ok": "●", "warning": "●", "error": "●", "muted": "○"}.get(state, "○")

    def set_loading(self, message: str = "Loading…") -> None:
        """Show a loading state in the panel body."""
        body_id = f"#{self.id}-body" if self.id else "#panel-body"
        try:
            body = self.query_one(body_id)
        except Exception:
            return
        body.remove_children()
        body.mount(Static(f"  {message}", classes="value--muted"))


class StatusItem(Static):
    """A single line status indicator: dot + label + value."""

    def __init__(
        self,
        label: str,
        value: str = "",
        state: str = "muted",
        *,
        id: str | None = None,
    ) -> None:
        dot = {"ok": "●", "warning": "●", "error": "●", "muted": "○"}.get(state, "○")
        css_class = f"value--{state}"
        super().__init__(
            f"{label}: {dot} {value}",
            id=id,
            classes=css_class,
        )
