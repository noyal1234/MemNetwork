"""brainkm configure — root Textual application."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from textual.app import App
from textual.binding import Binding

from brainkm.logging_config import install_tui_logging, restore_stderr_logging, set_tui_log_sink
from brainkm.tui.screens.actions import ActionsScreen
from brainkm.tui.screens.config_editor import ConfigEditorScreen
from brainkm.tui.screens.dashboard import DashboardScreen
from brainkm.tui.screens.wizard import WizardScreen
from brainkm.tui.widgets.command_palette import BrainkmCommandProvider

_CSS_PATH = Path(__file__).resolve().parent / "styles" / "app.tcss"


class BrainkmConfigureApp(App):
    """Full-screen TUI for configuring and operating the brainkm project brain.

    Screens:
        - dashboard: read-only status overview (Phase 1)
        - config: form-based config editing (Phase 2)
        - actions: service invocations with streamed output (Phase 3)
        - wizard: first-run guided setup (Phase 4)
    """

    TITLE = "brainkm configure"
    CSS_PATH = _CSS_PATH if _CSS_PATH.is_file() else None

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("question_mark", "help", "Help", show=True),
        Binding("d", "switch_screen('dashboard')", "Dashboard", show=True),
        Binding("c", "switch_screen('config')", "Config", show=True),
        Binding("a", "switch_screen('actions')", "Actions", show=True),
        Binding("w", "switch_screen('wizard')", "Wizard", show=True),
        Binding("slash", "command_palette", "Search", show=True),
    ]

    COMMANDS = App.COMMANDS | {BrainkmCommandProvider}

    SCREENS = {
        "dashboard": DashboardScreen,
        "config": ConfigEditorScreen,
        "actions": ActionsScreen,
        "wizard": WizardScreen,
    }

    def __init__(self, project_dir: Path | None = None) -> None:
        self._project_dir = project_dir
        # Bind screen factories to project_dir as an *instance* attribute
        # before calling super().__init__() — App.__init__() copies
        # self.SCREENS into its internal registry immediately, so setting
        # this after the super call would silently be ignored and every
        # screen would be built with project_dir=None (falling back to cwd).
        self.SCREENS = {
            "dashboard": lambda: DashboardScreen(project_dir=self._project_dir),
            "config": lambda: ConfigEditorScreen(project_dir=self._project_dir),
            "actions": lambda: ActionsScreen(project_dir=self._project_dir),
            "wizard": lambda: WizardScreen(project_dir=self._project_dir),
        }
        super().__init__()

    def on_mount(self) -> None:
        """Push the dashboard as the initial screen."""
        # Re-bind the sink now that the App instance exists. Console handlers
        # were already stripped in ``configure_cmd`` before App.run().
        install_tui_logging(sink=self._forward_service_log)

        project = self._project_dir or Path.cwd()
        brain_dir = project / ".brain"
        self.sub_title = str(project)

        if brain_dir.is_dir():
            self.push_screen("dashboard")
        else:
            # No .brain/ — start with wizard
            self.push_screen("wizard")

    def on_unmount(self) -> None:
        set_tui_log_sink(None)
        # cli.configure_cmd restores stderr in a finally block; keep this as a
        # safety net when the app is launched outside the CLI entrypoint.
        restore_stderr_logging()

    def _forward_service_log(self, message: str, levelno: int) -> None:
        """Route brainkm logger output into the Actions/Wizard RichLog if present."""
        # Logging handlers may fire from worker threads — hop onto the UI loop.
        try:
            if self._thread_id == threading.get_ident():
                self._write_service_log(message, levelno)
            else:
                self.call_from_thread(self._write_service_log, message, levelno)
        except Exception:
            # App not fully running yet (or already exiting).
            pass

    def _write_service_log(self, message: str, levelno: int) -> None:
        screen = self.screen
        log_panel = getattr(screen, "log_panel", None)
        if log_panel is None:
            return
        if levelno >= logging.ERROR:
            log_panel.log_error(message)
        elif levelno >= logging.WARNING:
            log_panel.log_warning(message)
        else:
            log_panel.log_plain(message)

    def action_help(self) -> None:
        """Show keybinding help overlay."""

        help_content = [
            ("q", "Quit application"),
            ("d", "Switch to Dashboard"),
            ("c", "Switch to Config Editor"),
            ("a", "Switch to Actions"),
            ("w", "Switch to Wizard"),
            ("r", "Refresh (Dashboard)"),
            ("/", "Open command palette (fuzzy search)"),
            ("y", "Approve (Review table)"),
            ("n", "Reject (Review table)"),
            ("Tab", "Next field (Forms)"),
            ("Escape", "Back / Close"),
            ("?", "Show this help"),
        ]

        # Use notify for quick help — a full overlay would be more complex
        lines = ["[bold]Keybindings:[/]"]
        for key, desc in help_content:
            lines.append(f"  [bold cyan]{key:>8}[/]  {desc}")
        self.notify("\n".join(lines), title="Help", severity="information", timeout=10)

    def switch_screen(self, screen_name: str) -> None:
        """Switch to a named screen, creating it if needed."""
        try:
            self.pop_screen()
        except Exception:
            pass
        self.push_screen(screen_name)
