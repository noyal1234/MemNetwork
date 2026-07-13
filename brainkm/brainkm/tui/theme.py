"""Color palette and theme tokens for the brainkm TUI.

Cyber-Industrial (DESIGN.md) — violet/obsidian surfaces with true red for
error/offline states (not Material soft-error pink).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------
# Used by app.tcss via Textual CSS variables and by Python code that needs
# programmatic access to colors (e.g. Rich markup in RichLog).

DARK = {
    "primary": "#d2bbff",
    "primary_container": "#7c3aed",
    "primary_muted": "#5a00c6",
    "success": "#4ae176",
    "warning": "#ffb95f",
    "error": "#ef4444",  # true red for offline/error (not #ffb4ab)
    "surface": "#15121b",
    "surface_alt": "#1d1a24",
    "surface_container": "#221e28",
    "surface_high": "#2c2833",
    "text": "#e8dfee",
    "text_muted": "#ccc3d8",
    "outline": "#958da1",
    "border": "#4a4455",
}

LIGHT = {
    "primary": "#6d28d9",
    "primary_container": "#7c3aed",
    "primary_muted": "#ede9fe",
    "success": "#16a34a",
    "warning": "#d97706",
    "error": "#dc2626",
    "surface": "#faf5ff",
    "surface_alt": "#f3e8ff",
    "surface_container": "#ede9fe",
    "surface_high": "#e9e4f5",
    "text": "#1e1b2e",
    "text_muted": "#6b7280",
    "outline": "#958da1",
    "border": "#d8b4fe",
}

# ---------------------------------------------------------------------------
# Status symbols — use both color + glyph for color-blind accessibility
# ---------------------------------------------------------------------------

STATUS_OK = ("●", "success")
STATUS_WARN = ("◆", "warning")
STATUS_ERR = ("✗", "error")
STATUS_UNKNOWN = ("○", "text_muted")


def escape_markup(text: str) -> str:
    """Escape literal ``[`` so Rich/Textual markup doesn't swallow it.

    Rich console markup treats ``[...]`` as style tags. Unknown tags (e.g. a
    literal ``[ Apply ]`` button label) are silently stripped to an empty
    string rather than raising — so any UI text containing an opening
    bracket must be escaped before being passed to a
    ``Static``/``Button``/``RichLog``.

    Only ``[`` needs escaping: Rich's markup parser only treats ``\\[`` as a
    special escape sequence, so escaping ``]`` too would leave a stray
    literal backslash in the rendered output (``]`` on its own is never
    treated as markup).
    """
    return text.replace("[", "\\[")


def bracket_label(text: str) -> str:
    """Build a markup-safe ``[ TEXT ]`` style label."""
    return escape_markup(f"[ {text} ]")


def status_markup(ok: bool | None, label: str) -> str:
    """Return Rich markup for a colored status indicator + label.

    Args:
        ok: True=green, False=red, None=grey.
        label: Text to display after the dot.
    """
    if ok is True:
        return f"[bold green]● {label}[/]"
    if ok is False:
        return f"[bold red]✗ {label}[/]"
    return f"[dim]○ {label}[/]"
