"""Color palette and theme tokens for the brainkm TUI.

Cyber-Industrial dark palette — violet/obsidian surfaces with true red for
error/offline states. When the terminal reports only 16 colors, ANSI-safe
named colors are applied at runtime via Textual CSS variable overrides.

Status value colors (StatusPanel ``value--*``):
  success / ok   — healthy, connected, match, fresh
  error          — unreachable, fail, Groq rate limit
  warning        — stale, mismatch, pending review
  accent #FFB000 — LLM model identifiers
  muted          — secondary facts (RAM, GPU, tier)
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Design tokens (truecolor / 256-color dark theme)
# ---------------------------------------------------------------------------

DARK = {
    "primary": "#d2bbff",
    "primary_container": "#7c3aed",
    "primary_muted": "#5a00c6",
    "success": "#4ae176",
    "warning": "#ffb95f",
    # Amber highlight for model IDs / important identity labels (user-picked).
    "accent": "#FFB000",
    "error": "#ef4444",
    "surface": "#15121b",
    "surface_alt": "#1d1a24",
    "surface_container": "#221e28",
    "surface_high": "#2c2833",
    "text": "#e8dfee",
    "text_muted": "#ccc3d8",
    "outline": "#958da1",
    "border": "#4a4455",
}

# ANSI-16 / limited-color fallback — named colors Textual maps to palette slots.
ANSI16 = {
    "primary": "magenta",
    "primary_container": "magenta",
    "primary_muted": "blue",
    "success": "green",
    "warning": "yellow",
    "accent": "yellow",
    "error": "red",
    "surface": "black",
    "surface_alt": "black",
    "surface_container": "black",
    "surface_high": "black",
    "text": "white",
    "text_muted": "white",
    "outline": "white",
    "border": "white",
}


def detect_color_depth() -> int:
    """Best-effort terminal color depth: 24 (truecolor), 8 (256), or 4 (ANSI-16)."""
    colorterm = (os.environ.get("COLORTERM") or "").lower()
    if "truecolor" in colorterm or "24bit" in colorterm:
        return 24
    term = (os.environ.get("TERM") or "").lower()
    if "256color" in term or "256" in term:
        return 8
    if term in {"dumb", ""}:
        return 4
    # Modern macOS/iTerm default to xterm-256color; assume 16 when unknown and narrow.
    if os.environ.get("BRAINKM_TUI_ANSI16") == "1":
        return 4
    return 8


def use_ansi16_palette() -> bool:
    """Return True when the TUI should switch to the ANSI-16 token set."""
    return detect_color_depth() <= 4


def active_tokens() -> dict[str, str]:
    """Return the color tokens for the current terminal capability."""
    return ANSI16 if use_ansi16_palette() else DARK


def ansi16_css_overrides() -> str:
    """Textual CSS that remaps design tokens to ANSI-16 named colors."""
    lines = ["/* ANSI-16 fallback tokens */"]
    mapping = [
        ("primary", "primary"),
        ("primary-container", "primary_container"),
        ("primary-muted", "primary_muted"),
        ("primary-light", "primary"),
        ("success", "success"),
        ("warning", "warning"),
        ("accent", "accent"),
        ("error", "error"),
        ("surface", "surface"),
        ("surface-alt", "surface_alt"),
        ("surface-container", "surface_container"),
        ("surface-high", "surface_high"),
        ("text", "text"),
        ("text-muted", "text_muted"),
        ("outline", "outline"),
        ("border", "border"),
    ]
    for css_name, key in mapping:
        lines.append(f"${css_name}: {ANSI16[key]};")
    return "\n".join(lines) + "\n"


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


def border_color_pair() -> tuple[str, str]:
    """Return (active, inactive) border colors for wizard step highlight."""
    tokens = active_tokens()
    return tokens["primary_container"], tokens["border"]
