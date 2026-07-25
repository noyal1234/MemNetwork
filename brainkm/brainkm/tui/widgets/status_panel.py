"""Reusable status card widget — ASCII title + key/value rows with status.

Color meaning for ``state`` (CSS ``value--*`` via Rich styles from theme tokens):
  ok      green  — healthy / connected / fresh
  error   red    — failure / unreachable / rate limit
  warning amber  — attention (stale, mismatch, pending work)
  accent  #FFB000 — model IDs (LLM identity)
  info    body text — factual system info (RAM, GPU, tier); not a health signal
  muted   gray   — secondary / n/a / loading placeholders

    Rows are rendered into a single body ``Static`` (Rich Text) so rapid refresh
never races Textual 8's async remove_children/mount.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import Static

from brainkm.tui.theme import active_tokens, escape_markup


class StatusPanel(Static):
    """A bordered card showing key/value rows with a colored status glyph.

    Usage::

        panel = StatusPanel(title="[ OLLAMA ]", id="ollama-panel")
        panel.set_items([
            ("Status", "reachable", "ok"),
            ("Model", "qwen2.5:3b", "accent"),
            ("Tier", "standard", "info"),
        ])
    """

    DEFAULT_CSS = """
    StatusPanel {
        height: auto;
    }

    StatusPanel .panel-body {
        height: auto;
        width: 100%;
    }

    StatusPanel.-loading {
        opacity: 0.75;
    }
    """

    _LABEL_WIDTH = 14

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
        yield Static("", id=f"{self.id}-body" if self.id else "panel-body", classes="panel-body")

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
                   state is one of: "ok", "warning", "error", "muted", "accent", "info".
        """
        self._items = [(label, str(value or ""), state) for label, value, state in items]
        self.remove_class("-loading")
        self._render_items()

    def set_loading(self, message: str = "Loading…") -> None:
        """Show a loading state in the panel body."""
        self.add_class("-loading")
        self._items = [("Status", message, "muted")]
        self._render_items()

    def set_error(self, message: str) -> None:
        """Show a panel-level error state."""
        self.remove_class("-loading")
        self._items = [
            ("Status", "error", "error"),
            ("Detail", message[:72], "muted"),
        ]
        self._render_items()

    def _render_items(self) -> None:
        body_id = f"#{self.id}-body" if self.id else "#panel-body"
        try:
            body = self.query_one(body_id, Static)
        except Exception:
            return
        tokens = active_tokens()
        state_color = {
            "ok": tokens["success"],
            "warning": tokens["warning"],
            "error": tokens["error"],
            "accent": tokens["accent"],
            "info": tokens["text"],
            "muted": tokens["text_muted"],
        }
        text = Text()
        for i, (label, value, state) in enumerate(self._items):
            if i:
                text.append("\n")
            # Empty label = wrapped continuation line (Notes / Auth / DualWriter).
            if label.strip():
                label_col = f"{label}:".ljust(self._LABEL_WIDTH)
            else:
                label_col = " " * self._LABEL_WIDTH
            text.append(label_col, style=tokens["text_muted"])
            glyph = self._state_glyph(state)
            color = state_color.get(state, tokens["text_muted"])
            display = value if value else "—"
            # Continuation lines: omit repeating glyph for cleaner wrap.
            if label.strip():
                text.append(f"{glyph} ", style=f"bold {color}")
            else:
                text.append("  ", style=color)
            text.append(display, style=f"bold {color}")
        body.update(text)

    def _state_glyph(self, state: str) -> str:
        return {
            "ok": "●",
            "warning": "◆",
            "error": "✗",
            "muted": "○",
            "accent": "◆",
            "info": "●",
        }.get(state, "○")
