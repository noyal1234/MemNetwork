"""Scrolling rich-text log panel for streaming service output."""

from __future__ import annotations

from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import RichLog, Static

from brainkm.tui.theme import escape_markup


class RichLogPanel(Vertical):
    """A titled panel wrapping a ``RichLog`` for streaming action output."""

    DEFAULT_CSS = """
    RichLogPanel {
        height: 1fr;
        min-height: 12;
    }

    RichLogPanel RichLog {
        height: 1fr;
        min-height: 10;
        background: $surface;
        color: $text;
        border: none;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        title: str = "Log",
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=f"rich-log-panel {classes or ''}")
        self._title = title

    def compose(self) -> ComposeResult:
        yield Static(escape_markup(self._title), classes="log-title")
        yield RichLog(
            highlight=True,
            markup=True,
            wrap=True,
            auto_scroll=True,
            id=f"{self.id}-richlog" if self.id else "richlog",
        )

    @property
    def rich_log(self) -> RichLog:
        log_id = f"#{self.id}-richlog" if self.id else "#richlog"
        return self.query_one(log_id, RichLog)

    def _timestamp(self) -> str:
        return datetime.now().strftime("%H:%M:%S")  # noqa: DTZ005

    def log_info(self, message: str) -> None:
        """Write an informational line with timestamp."""
        self.rich_log.write(f"[dim]{self._timestamp()}[/] {escape_markup(message)}")

    def log_success(self, message: str) -> None:
        """Write a success line with green checkmark."""
        self.rich_log.write(
            f"[dim]{self._timestamp()}[/] [bold green]✓[/] {escape_markup(message)}"
        )

    def log_error(self, message: str) -> None:
        """Write an error line with red cross."""
        self.rich_log.write(
            f"[dim]{self._timestamp()}[/] [bold red]✗[/] {escape_markup(message)}"
        )

    def log_warning(self, message: str) -> None:
        """Write a warning line."""
        self.rich_log.write(
            f"[dim]{self._timestamp()}[/] [bold yellow]●[/] {escape_markup(message)}"
        )

    def log_plain(self, message: str) -> None:
        """Write a plain line (no timestamp)."""
        self.rich_log.write(f"  {escape_markup(message)}")

    def clear(self) -> None:
        """Clear all log output."""
        self.rich_log.clear()
