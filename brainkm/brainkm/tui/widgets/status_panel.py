"""Reusable status card widget — ASCII title + key/value rows with status."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from brainkm.tui.theme import escape_markup


class StatusPanel(Static):
    """A bordered card showing key/value rows with a colored status glyph.

    Usage::

        panel = StatusPanel(title="[ OLLAMA ]", id="ollama-panel")
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

    /* Textual's Vertical defaults to height:1fr — inside an auto-height
       ancestor (e.g. a doctor-row) that makes this panel (and its siblings)
       balloon to fill all remaining space. Force it back to content-height. */
    StatusPanel > Vertical {
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
        super().__init__(id=id, classes=f"status-panel {classes or ''}".strip())
        self._title = title
        self._items: list[tuple[str, str, str]] = []

    def compose(self) -> ComposeResult:
        if self._title:
            yield Static(escape_markup(self._title), classes="panel-title")
        yield Vertical(id=f"{self.id}-body" if self.id else "panel-body")

    def set_title(self, title: str) -> None:
        """Update the panel title text."""
        self._title = title
        try:
            self.query_one(".panel-title", Static).update(escape_markup(title))
        except Exception:
            pass

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
            glyph = self._state_glyph(state)
            row = Horizontal(classes="status-row")
            body.mount(row)
            row.mount(
                Static(f"  {escape_markup(label)}:", classes="status-label"),
                Static(
                    f"{glyph} {escape_markup(value)}",
                    classes=f"status-value value--{state}",
                ),
            )

    def _state_glyph(self, state: str) -> str:
        return {"ok": "●", "warning": "◆", "error": "✗", "muted": "○"}.get(state, "○")

    def set_loading(self, message: str = "Loading…") -> None:
        """Show a loading state in the panel body."""
        body_id = f"#{self.id}-body" if self.id else "#panel-body"
        try:
            body = self.query_one(body_id)
        except Exception:
            return
        body.remove_children()
        body.mount(Static(f"  {escape_markup(message)}", classes="value--muted"))


class StatusItem(Static):
    """A single line status indicator: glyph + label + value."""

    def __init__(
        self,
        label: str,
        value: str = "",
        state: str = "muted",
        *,
        id: str | None = None,
    ) -> None:
        glyph = {"ok": "●", "warning": "◆", "error": "✗", "muted": "○"}.get(state, "○")
        css_class = f"value--{state}"
        super().__init__(
            f"{label}: {glyph} {value}",
            id=id,
            classes=css_class,
        )
