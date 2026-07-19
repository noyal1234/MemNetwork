"""Fuzzy command search — thin wrapper around Textual's built-in command palette.

Provides a single `Provider` (`BrainkmCommandProvider`) that surfaces two kinds
of hits when the user opens the palette with `/` (or the default `ctrl+p`):

1. **Navigation** — jump straight to any of the four app screens, or quit.
2. **CLI reference** — every command registered on the live Typer app
   (`brainkm.cli.app`), discovered via introspection so the palette can never
   drift out of sync with the actual CLI surface (see
   `enumerate_cli_commands`). Selecting one shows its help text and, for
   commands that map onto something the TUI can already do (e.g. `review
   list` -> Actions screen), jumps there directly.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from textual.command import DiscoveryHit, Hit, Hits, Provider

if TYPE_CHECKING:
    pass

# Maps a CLI command's full name (e.g. "graph sync") to the TUI screen that
# lets the user run the equivalent action, so palette hits can jump straight
# there instead of merely describing the command.
_COMMAND_TO_SCREEN: dict[str, str] = {
    "configure": "dashboard",
    "graph sync": "actions",
    "graph status": "actions",
    "graph import": "actions",
    "graph extract": "actions",
    "bench run": "actions",
    "review list": "dashboard",
    "review approve": "dashboard",
    "review reject": "dashboard",
    "ollama doctor": "actions",
    "ollama apply": "actions",
    "groq doctor": "actions",
    "export": "actions",
    "repair": "actions",
    "viz": "actions",
    "install": "wizard",
}

_NAV_COMMANDS: tuple[tuple[str, str, str], ...] = (
    ("dashboard", "Go to Dashboard", "Brain status, Ollama/Groq/Graph health, review queue"),
    ("config", "Go to Config Editor", "Edit .brain/config.json via validated forms"),
    ("actions", "Go to Actions", "Run graph sync, viz, bench suites, doctor checks, export, repair"),
    ("wizard", "Go to Wizard", "Guided first-run setup"),
)


def enumerate_cli_commands() -> list[dict[str, str]]:
    """Walk the live Typer/Click app tree to discover every registered command.

    Uses duck-typing (`hasattr(cmd, "commands")`) rather than
    `isinstance(cmd, click.Group)` — Typer vendors its own Click fork
    (`typer._click.core.Command`), so `isinstance` checks against the
    top-level `click` package silently fail to recognize Typer sub-groups
    such as `graph`, `bench`, `review`, `ollama`, and `groq`.
    """
    import typer

    from brainkm.cli import app as typer_app

    root = typer.main.get_command(typer_app)

    def walk(group: Any, prefix: str = "") -> list[dict[str, str]]:
        found: list[dict[str, str]] = []
        for name, cmd in sorted(group.commands.items()):
            full = f"{prefix} {name}".strip()
            if hasattr(cmd, "commands"):
                found.extend(walk(cmd, full))
            else:
                help_text = (cmd.help or cmd.short_help or "").split("\n")[0]
                found.append({"name": full, "help": help_text})
        return found

    return walk(root)


class BrainkmCommandProvider(Provider):
    """Command palette provider: screen navigation + CLI command reference."""

    async def startup(self) -> None:
        try:
            self._cli_commands = enumerate_cli_commands()
        except Exception:
            # Introspection is best-effort — navigation hits must still work
            # even if the CLI module fails to import for some reason.
            self._cli_commands = []

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)

        for screen_name, title, help_text in _NAV_COMMANDS:
            score = matcher.match(f"{title} {help_text}")
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(title),
                    partial(self.app.switch_screen, screen_name),
                    help=help_text,
                )

        yield Hit(
            1.0 if not query else matcher.match("quit exit"),
            matcher.highlight("Quit"),
            self.app.action_quit,
            help="Exit brainkm configure",
        )

        for entry in self._cli_commands:
            label = f"brainkm {entry['name']}"
            score = matcher.match(f"{label} {entry['help']}")
            if score > 0:
                screen_name = _COMMAND_TO_SCREEN.get(entry["name"])
                command = (
                    partial(self.app.switch_screen, screen_name)
                    if screen_name
                    else partial(self._show_cli_reference, label, entry["help"])
                )
                yield Hit(
                    score,
                    matcher.highlight(label),
                    command,
                    help=entry["help"] or "Run via terminal: " + label,
                )

    def _show_cli_reference(self, label: str, help_text: str) -> None:
        self.app.notify(
            help_text or "Run this from a terminal.",
            title=label,
            severity="information",
            timeout=6,
        )

    async def discover(self) -> Hits:
        """Hits shown before the user types anything."""
        for screen_name, title, help_text in _NAV_COMMANDS:
            yield DiscoveryHit(
                title,
                partial(self.app.switch_screen, screen_name),
                help=help_text,
            )
