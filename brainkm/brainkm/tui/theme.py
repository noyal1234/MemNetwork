"""Color palette and theme tokens for the brainkm TUI."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------
# Used by app.tcss via Textual CSS variables and by Python code that needs
# programmatic access to colors (e.g. Rich markup in RichLog).

DARK = {
    "primary": "#7c3aed",
    "primary_muted": "#4c1d95",
    "success": "#22c55e",
    "warning": "#f59e0b",
    "error": "#ef4444",
    "surface": "#1e1b2e",
    "surface_alt": "#2d2640",
    "text": "#e2e0ea",
    "text_muted": "#8b83a0",
    "border": "#3f3663",
}

LIGHT = {
    "primary": "#6d28d9",
    "primary_muted": "#ede9fe",
    "success": "#16a34a",
    "warning": "#d97706",
    "error": "#dc2626",
    "surface": "#faf5ff",
    "surface_alt": "#f3e8ff",
    "text": "#1e1b2e",
    "text_muted": "#6b7280",
    "border": "#d8b4fe",
}

# ---------------------------------------------------------------------------
# Status symbols — use both color + glyph for color-blind accessibility
# ---------------------------------------------------------------------------

STATUS_OK = ("●", "success")
STATUS_WARN = ("●", "warning")
STATUS_ERR = ("●", "error")
STATUS_UNKNOWN = ("○", "text_muted")


def status_markup(ok: bool | None, label: str) -> str:
    """Return Rich markup for a colored status indicator + label.

    Args:
        ok: True=green, False=red, None=grey.
        label: Text to display after the dot.
    """
    if ok is True:
        return f"[bold green]● {label}[/]"
    if ok is False:
        return f"[bold red]● {label}[/]"
    return f"[dim]○ {label}[/]"
