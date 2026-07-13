"""Tests for TUI-safe logging (stderr must not paint over Textual)."""

from __future__ import annotations

import io
import logging
import sys
from pathlib import Path

from brainkm.logging_config import (
    _TuiLogHandler,
    configure_logging,
    get_logger,
    install_tui_logging,
    restore_stderr_logging,
    set_tui_log_sink,
)
from brainkm.tui.app import BrainkmConfigureApp
from brainkm.tui.widgets.rich_log_panel import RichLogPanel


def _console_stream_handlers() -> list[logging.Handler]:
    root = logging.getLogger("brainkm")
    return [
        h
        for h in root.handlers
        if isinstance(h, logging.StreamHandler) and not isinstance(h, _TuiLogHandler)
    ]


def test_install_tui_logging_removes_stderr_handlers() -> None:
    restore_stderr_logging()
    root = logging.getLogger("brainkm")
    root.handlers.clear()
    configure_logging()
    assert _console_stream_handlers(), "expected a StreamHandler before TUI install"

    captured: list[str] = []
    install_tui_logging(sink=lambda msg, _lvl: captured.append(msg))
    try:
        assert not _console_stream_handlers()
        assert any(isinstance(h, _TuiLogHandler) for h in root.handlers)
        get_logger("test.tui").info("hello from worker")
        assert any("hello from worker" in m for m in captured)
    finally:
        restore_stderr_logging()
        set_tui_log_sink(None)


def test_install_tui_logging_works_after_stderr_is_replaced() -> None:
    """Regression: Textual replaces sys.stderr before on_mount.

    Comparing handler.stream to the *current* sys.stderr missed the live
    StreamHandler and migration INFO lines painted above the TUI.
    """
    restore_stderr_logging()
    root = logging.getLogger("brainkm")
    root.handlers.clear()
    configure_logging()
    assert _console_stream_handlers()

    # Simulate Textual wrapping/replacing stderr after logging was configured.
    fake = io.StringIO()
    original = sys.stderr
    sys.stderr = fake  # type: ignore[assignment]
    try:
        install_tui_logging(sink=None)
        assert not _console_stream_handlers()
        get_logger("db.migrate").info("Applying migration 002_temporal_lite")
        assert "Applying migration" not in fake.getvalue()
    finally:
        sys.stderr = original
        restore_stderr_logging()
        set_tui_log_sink(None)


async def test_action_bench_does_not_crash_and_writes_log(tui_project: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tui_project)
    async with app.run_test(size=(140, 60)) as pilot:
        app.switch_screen("actions")
        await pilot.pause(0.3)
        await pilot.click("#btn-bench-token")
        await pilot.pause(2.5)
        log = app.screen.query_one("#action-log", RichLogPanel)
        assert len(log.rich_log.lines) >= 1
