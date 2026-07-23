"""Multi-select app picker with radio-style ○/● indicators."""

from __future__ import annotations

from textual.content import Content
from textual.style import Style
from textual.widgets import Checkbox


class AppPickCheckbox(Checkbox):
    """Checkbox that looks like a radio (○/●) but stays multi-select.

    Used by the configure wizard client step so selected apps are obvious
    and row widths align (see ``#wizard-app-list`` in app.tcss).
    """

    BUTTON_LEFT = " "
    BUTTON_INNER = "●"
    BUTTON_RIGHT = " "
    DEFAULT_CLASSES = "app-pick"

    @property
    def _button(self) -> Content:
        button_style = self.get_visual_style("toggle--button")
        side_style = Style(
            foreground=button_style.background,
            background=self.background_colors[1],
        )
        inner = "●" if self.value else "○"
        return Content.assemble(
            (self.BUTTON_LEFT, side_style),
            (inner, button_style),
            (self.BUTTON_RIGHT, side_style),
        )
