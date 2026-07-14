"""Reusable status card widget — ASCII title + key/value rows with status.

Color meaning for ``state`` (CSS ``value--*``):
  ok      green  — healthy / connected / fresh
  error   red    — failure / unreachable / rate limit
  warning amber  — attention (stale, mismatch, pending work)
  accent  #FFB000 — model IDs (LLM identity)
  muted   gray   — informational / secondary
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from brainkm.tui.theme import escape_markup

# States whose values are model IDs — always render with accent styling if passed
# through as "accent". Callers should use state="accent" for model strings.


class StatusPanel(Static):
    """A bordered card showing key/value rows with a colored status glyph.

    Usage::

        panel = StatusPanel(title="[ OLLAMA ]", id="ollama-panel")
        panel.set_items([
            ("Status", "reachable", "ok"),
            ("Model", "qwen2.5:3b", "accent"),
            ("Tier", "standard", "muted"),
        ])
    """

    DEFAULT_CSS = """
    StatusPanel {
        height: auto;
    }

    StatusPanel > Vertical {
        height: auto;
        width: 100%;
    }

    StatusPanel .status-row {
        height: 1;
        width: 100%;
        layout: horizontal;
    }

    StatusPanel .status-label {
        width: 12;
        color: $text-muted;
        text-wrap: nowrap;
        overflow-x: hidden;
        text-overflow: ellipsis;
        padding: 0 1 0 0;
    }

    StatusPanel .status-glyph {
        width: 2;
        text-align: left;
    }

    StatusPanel .status-value {
        width: 1fr;
        height: 1;
        text-wrap: nowrap;
        overflow-x: hidden;
        text-overflow: ellipsis;
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
                   state is one of: "ok", "warning", "error", "muted", "accent".
        """
        self._items = [(label, str(value or ""), state) for label, value, state in items]
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
            # Three columns so glyphs and values share a vertical baseline.
            # markup=False on values: Rich silently drops unknown [...] tags.
            row = Horizontal(classes="status-row")
            body.mount(row)
            row.mount(
                Static(f"{escape_markup(label)}:", classes="status-label"),
                Static(
                    glyph,
                    classes=f"status-glyph value--{state}",
                    markup=False,
                ),
                Static(
                    value if value else "—",
                    classes=f"status-value value--{state}",
                    markup=False,
                ),
            )

    def _state_glyph(self, state: str) -> str:
        return {
            "ok": "●",
            "warning": "◆",
            "error": "✗",
            "muted": "○",
            "accent": "◆",
        }.get(state, "○")

    def set_loading(self, message: str = "Loading…") -> None:
        """Show a loading state in the panel body."""
        self.set_items([("Status", message, "muted")])
