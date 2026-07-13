"""Review queue DataTable widget."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.widgets import DataTable, Static


class ReviewTable(Static):
    """DataTable showing pending review items with approve/reject actions.

    Emits ``ReviewTable.Approved`` and ``ReviewTable.Rejected`` messages
    when the user presses ``y`` or ``n`` on a selected row.
    """

    class Approved(Message):
        """User approved a neuron."""

        def __init__(self, node_id: str) -> None:
            super().__init__()
            self.node_id = node_id

    class Rejected(Message):
        """User rejected a neuron."""

        def __init__(self, node_id: str) -> None:
            super().__init__()
            self.node_id = node_id

    def __init__(
        self,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes or "")
        self._items: list[dict] = []

    def compose(self) -> ComposeResult:
        table = DataTable(id="review-data-table", cursor_type="row")
        table.add_columns("ID", "Subtype", "Confidence", "Title")
        yield table

    @property
    def table(self) -> DataTable:
        return self.query_one("#review-data-table", DataTable)

    def set_items(self, items: list[dict]) -> None:
        """Populate the table with review items.

        Each item should have keys: node_id, subtype, confidence, title.
        """
        self._items = items
        table = self.table
        table.clear()
        for item in items:
            node_id = item.get("node_id", "")
            # Truncate ID for display
            short_id = f"{node_id[:8]}…" if len(node_id) > 8 else node_id
            table.add_row(
                short_id,
                item.get("subtype", ""),
                f"{item.get('confidence', 0):.2f}",
                self._truncate(item.get("title", ""), 40),
                key=node_id,
            )

    def set_empty(self, message: str = "No pending review items.") -> None:
        """Show an empty state."""
        table = self.table
        table.clear()
        self._items = []
        # Add a single row with the message
        table.add_row(message, "", "", "", key="__empty__")

    def _truncate(self, text: str, max_len: int) -> str:
        if len(text) <= max_len:
            return text
        return text[: max_len - 1] + "…"

    def get_selected_node_id(self) -> str | None:
        """Return the node_id of the currently selected row."""
        table = self.table
        if table.cursor_row is not None and table.cursor_row < len(self._items):
            return self._items[table.cursor_row].get("node_id")
        return None

    def key_y(self) -> None:
        """Approve the selected neuron."""
        node_id = self.get_selected_node_id()
        if node_id:
            self.post_message(self.Approved(node_id))

    def key_n(self) -> None:
        """Reject the selected neuron."""
        node_id = self.get_selected_node_id()
        if node_id:
            self.post_message(self.Rejected(node_id))
