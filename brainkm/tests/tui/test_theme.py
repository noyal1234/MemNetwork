"""Unit tests for TUI theme helpers (ANSI-16 fallback)."""

from __future__ import annotations

from brainkm.tui.theme import (
    ANSI16,
    DARK,
    active_tokens,
    ansi16_css_overrides,
    detect_color_depth,
    use_ansi16_palette,
)


def test_detect_truecolor(monkeypatch) -> None:
    monkeypatch.setenv("COLORTERM", "truecolor")
    monkeypatch.delenv("BRAINKM_TUI_ANSI16", raising=False)
    assert detect_color_depth() == 24
    assert use_ansi16_palette() is False
    assert active_tokens() is DARK


def test_force_ansi16(monkeypatch) -> None:
    monkeypatch.setenv("BRAINKM_TUI_ANSI16", "1")
    monkeypatch.delenv("COLORTERM", raising=False)
    monkeypatch.setenv("TERM", "xterm")
    assert use_ansi16_palette() is True
    assert active_tokens() is ANSI16
    css = ansi16_css_overrides()
    assert "$error: red;" in css
    assert "$primary: magenta;" in css
