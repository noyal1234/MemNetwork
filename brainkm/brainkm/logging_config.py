"""Structured logging setup for brainkm."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable

from brainkm.config import get_settings

# Callback installed by the Textual TUI so service INFO lines land in RichLog
# instead of painting over the alternate screen via stderr.
_tui_sink: Callable[[str, int], None] | None = None
_tui_mode: bool = False
_stderr_handlers: list[logging.Handler] = []


class _TuiLogHandler(logging.Handler):
    """Forward log records to the active TUI sink (never to the terminal)."""

    def emit(self, record: logging.LogRecord) -> None:
        sink = _tui_sink
        if sink is None:
            return
        try:
            sink(self.format(record), record.levelno)
        except Exception:
            self.handleError(record)


def configure_logging() -> None:
    """Configure root logger once (idempotent)."""
    settings = get_settings()
    root = logging.getLogger("brainkm")
    if root.handlers:
        return

    # Never attach stderr while the TUI owns the terminal — Textual replaces
    # sys.stderr, and StreamHandler output paints over the alternate screen.
    if _tui_mode:
        handler: logging.Handler = _TuiLogHandler()
        handler.setFormatter(logging.Formatter(fmt="%(levelname)s %(name)s %(message)s"))
    else:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger under brainkm."""
    configure_logging()
    return logging.getLogger(f"brainkm.{name}")


def install_tui_logging(sink: Callable[[str, int], None] | None = None) -> None:
    """Detach console StreamHandlers so Textual's screen is not corrupted.

    Must run *before* ``App.run()`` when possible. Do not compare handler
    streams to ``sys.stderr`` — Textual replaces stderr during startup, which
    made the old identity check miss the live StreamHandler (logs then
    appeared above / on top of the TUI).

    Optionally install ``sink(message, levelno)`` to receive brainkm log lines
    (e.g. forward into the Actions RichLog). Safe to call more than once.
    """
    global _tui_sink, _tui_mode
    _tui_mode = True
    _tui_sink = sink
    configure_logging()
    root = logging.getLogger("brainkm")

    # Strip every console StreamHandler. Do not key off sys.stderr identity —
    # after Textual starts, that comparison is unreliable.
    for handler in list(root.handlers):
        if isinstance(handler, _TuiLogHandler):
            continue
        if isinstance(handler, logging.StreamHandler):
            _stderr_handlers.append(handler)
            root.removeHandler(handler)

    if not any(isinstance(h, _TuiLogHandler) for h in root.handlers):
        tui_handler = _TuiLogHandler()
        tui_handler.setFormatter(logging.Formatter(fmt="%(levelname)s %(name)s %(message)s"))
        tui_handler.setLevel(logging.INFO)
        root.addHandler(tui_handler)


def set_tui_log_sink(sink: Callable[[str, int], None] | None) -> None:
    """Update or clear the live TUI log sink without reinstalling handlers."""
    global _tui_sink
    _tui_sink = sink


def restore_stderr_logging() -> None:
    """Restore stderr handlers after the TUI exits."""
    global _tui_sink, _tui_mode
    _tui_sink = None
    _tui_mode = False
    root = logging.getLogger("brainkm")
    for handler in list(root.handlers):
        if isinstance(handler, _TuiLogHandler):
            root.removeHandler(handler)
            handler.close()
    for handler in _stderr_handlers:
        if handler not in root.handlers:
            root.addHandler(handler)
    _stderr_handlers.clear()

    # If nothing is left (e.g. TUI started before configure_logging), restore
    # a normal stderr handler so CLI commands after configure still log.
    if not root.handlers:
        configure_logging()
