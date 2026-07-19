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
        width: 15;
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

    StatusPanel.-loading {
        opacity: 0.75;
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
        self._render_generation = 0

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
        self.remove_class("-loading")
        self._schedule_render()

    def set_loading(self, message: str = "Loading…") -> None:
        """Show a loading state in the panel body."""
        self.add_class("-loading")
        self._items = [("Status", message, "muted")]
        self._schedule_render()

    def set_error(self, message: str) -> None:
        """Show a panel-level error state."""
        self.remove_class("-loading")
        self._items = [
            ("Status", "error", "error"),
            ("Detail", message[:72], "muted"),
        ]
        self._schedule_render()

    def _schedule_render(self) -> None:
        """Queue an awaited DOM rebuild on the main loop (Textual 8-safe)."""
        if not self.is_mounted:
            return
        self._render_generation += 1
        generation = self._render_generation
        group = f"status-render-{self.id or id(self)}"
        self.run_worker(
            self._render_items_async(generation),
            exclusive=True,
            group=group,
            exit_on_error=False,
        )

    async def _render_items_async(self, generation: int) -> None:
        if generation != self._render_generation:
            return
        body_id = f"#{self.id}-body" if self.id else "#panel-body"
        try:
            body = self.query_one(body_id)
        except Exception:
            return
        await body.remove_children()
        if generation != self._render_generation:
            return
        items = list(self._items)
        children: list[Horizontal] = []
        for label, value, state in items:
            glyph = self._state_glyph(state)
            row = Horizontal(
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
                classes="status-row",
            )
            children.append(row)
        if children:
            await body.mount(*children)

    def _state_glyph(self, state: str) -> str:
        return {
            "ok": "●",
            "warning": "◆",
            "error": "✗",
            "muted": "○",
            "accent": "◆",
        }.get(state, "○")
