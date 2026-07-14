"""Dynamic config form widget — renders BrainConfig sections as Textual form fields."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Input, Label, Select, Static, Switch

from brainkm.services.distill_status import distill_mode_select_options

# ---------------------------------------------------------------------------
# Field descriptors for each BrainConfig section
# ---------------------------------------------------------------------------

SECTION_FIELDS: dict[str, list[dict[str, Any]]] = {
    "capture": [
        {
            "key": "distill_mode",
            "label": "Distill Mode",
            "type": "select",
            # Primary modes only; ``rules`` appears only if already active in config.
            "options": distill_mode_select_options(),
            "help": (
                "How to extract neurons from transcripts. "
                "Cursor mode includes a free heuristic; Agent CLI only upgrades it. "
                "Ollama/Groq are separate LLM backends."
            ),
        },
        {
            "key": "max_auto_neurons_per_session",
            "label": "Max Auto Neurons / Session",
            "type": "int",
            "min": 1,
            "max": 500,
            "help": "Maximum neurons auto-captured per session",
        },
        {
            "key": "max_neurons_per_plan",
            "label": "Max Neurons / Plan",
            "type": "int",
            "min": 1,
            "max": 200,
            "help": "Maximum neurons extracted per plan file",
        },
    ],
    "ollama": [
        {
            "key": "model",
            "label": "Model",
            "type": "str",
            "help": "Ollama model name (e.g. qwen2.5:3b)",
        },
        {
            "key": "auto_select_model",
            "label": "Auto-select Model",
            "type": "bool",
            "help": "Let brainkm doctor pick the best model for your hardware",
        },
        {
            "key": "timeout_seconds",
            "label": "Timeout (seconds)",
            "type": "int",
            "min": 5,
            "max": 600,
            "help": "Request timeout for Ollama API calls",
        },
        {
            "key": "base_url",
            "label": "Base URL",
            "type": "str",
            "help": "Ollama API endpoint",
        },
    ],
    "groq": [
        {
            "key": "model",
            "label": "Model",
            "type": "str",
            "help": "Groq model name",
        },
        {
            "key": "timeout_seconds",
            "label": "Timeout (seconds)",
            "type": "int",
            "min": 5,
            "max": 300,
            "help": "Request timeout for Groq API calls",
        },
        {
            "key": "base_url",
            "label": "Base URL",
            "type": "str",
            "help": "Groq API endpoint",
        },
    ],
    "budget": [
        {
            "key": "total_tokens",
            "label": "Total Token Budget",
            "type": "int",
            "min": 100,
            "max": 8000,
            "help": "Hard cap on injection pack tokens (default 1500)",
        },
        {
            "key": "dynamic_reallocation",
            "label": "Dynamic Reallocation",
            "type": "bool",
            "help": "Allow budget slots to redistribute unused tokens",
        },
    ],
    "recall": [
        {
            "key": "abstain_on_low_confidence",
            "label": "Abstain on Low Confidence",
            "type": "bool",
            "help": "Return empty results instead of low-quality matches",
        },
        {
            "key": "abstain_mode",
            "label": "Abstain Mode",
            "type": "select",
            "options": ["percentile", "absolute"],
            "help": "How to determine the abstention threshold",
        },
        {
            "key": "abstain_percentile",
            "label": "Abstain Percentile",
            "type": "float",
            "min": 0.0,
            "max": 1.0,
            "help": "Percentile threshold (0.0 – 1.0) for corpus BM25 scores",
        },
    ],
    "injection": [
        {
            "key": "session_start",
            "label": "SessionStart Injection",
            "type": "bool",
            "help": "Inject brain pack at session start",
        },
        {
            "key": "frozen_snapshot",
            "label": "Frozen Snapshot",
            "type": "bool",
            "help": "Freeze injection pack at session start (no mid-session mutation)",
        },
        {
            "key": "max_recalls_per_turn",
            "label": "Max Recalls / Turn",
            "type": "int",
            "min": 0,
            "max": 5,
            "help": "Maximum recall tool calls per agent turn",
        },
    ],
    "handover": [
        {
            "key": "precompact_enabled",
            "label": "PreCompact Enabled",
            "type": "bool",
            "help": "Distill transcript before Cursor compaction",
        },
        {
            "key": "precompact_distill_timeout_seconds",
            "label": "Distill Timeout (s)",
            "type": "int",
            "min": 1,
            "max": 60,
            "help": "Timeout for PreCompact distill operation",
        },
        {
            "key": "export_markdown",
            "label": "Export Markdown",
            "type": "bool",
            "help": "Export markdown snapshot during handover",
        },
    ],
    "graphify": [
        {
            "key": "enabled",
            "label": "Graphify Enabled",
            "type": "bool",
            "help": "Enable AST code graph integration",
        },
        {
            "key": "code_only",
            "label": "Code Only",
            "type": "bool",
            "help": "Import only code nodes (skip docs/papers)",
        },
        {
            "key": "extract_timeout_seconds",
            "label": "Extract Timeout (s)",
            "type": "int",
            "min": 30,
            "max": 1800,
            "help": "Timeout for graphify extract subprocess",
        },
        {
            "key": "auto_sync.enabled",
            "label": "Auto Sync",
            "type": "bool",
            "help": "Background sync via MCP scheduler (PostToolUse flag)",
        },
        {
            "key": "auto_sync.watch_filesystem",
            "label": "Watch Filesystem",
            "type": "bool",
            "help": "Opt-in: watch source files for multi-IDE edits (restart MCP after change)",
        },
    ],
}


class ConfigForm(Vertical):
    """A form section for one BrainConfig sub-model.

    Reads current values from a config dict and renders editable fields.
    Emits ``ConfigForm.Changed`` with the updated section dict on any edit.

    Extends ``Vertical`` (not ``Static``) so height sizes to composed fields;
    otherwise later sections (Ollama, budget, …) sit clipped inside
    ``#config-forms`` and never become scrollable.
    """

    class Changed(Message):
        """A config field was edited."""

        def __init__(self, section: str, data: dict[str, Any]) -> None:
            super().__init__()
            self.section = section
            self.data = data

    def __init__(
        self,
        section: str,
        values: dict[str, Any],
        *,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id, classes="config-section")
        self._section = section
        self._values = dict(values)
        self._fields = SECTION_FIELDS.get(section, [])

    def compose(self) -> ComposeResult:
        title = self._section.replace("_", " ").title()
        yield Static(f"⚙  {title}", classes="section-title")

        for field in self._fields:
            key = field["key"]
            current = self._get_nested(key)
            # Nested keys use "__" in widget IDs (dots are invalid / ambiguous).
            field_id = f"field-{self._section}-{key.replace('.', '__')}"

            with Vertical(classes="config-field"):
                with Horizontal(classes="config-field-row"):
                    yield Label(f"{field['label']}:", classes="field-label")

                    if field["type"] == "bool":
                        yield Switch(value=bool(current), id=field_id)
                    elif field["type"] == "select":
                        options = self._select_options(field["options"])
                        if key == "distill_mode":
                            options = distill_mode_select_options(
                                current=str(current) if current else None,
                            )
                        yield Select(
                            options,
                            value=str(current),
                            id=field_id,
                            allow_blank=False,
                        )
                    elif field["type"] in ("int", "float"):
                        yield Input(
                            value=str(current if current is not None else ""),
                            id=field_id,
                            type="number",
                        )
                    else:
                        yield Input(
                            value=str(current if current is not None else ""),
                            id=field_id,
                            type="text",
                        )

                if field.get("help"):
                    yield Static(field["help"], classes="field-help")

    def on_input_changed(self, event: Input.Changed) -> None:
        self._update_from_field(event.input.id or "", event.value)

    def on_switch_changed(self, event: Switch.Changed) -> None:
        self._update_from_field(event.switch.id or "", event.value)

    def on_select_changed(self, event: Select.Changed) -> None:
        self._update_from_field(str(event.select.id or ""), event.value)

    def _update_from_field(self, field_id: str, raw_value: Any) -> None:
        """Parse the field ID, coerce the value, and emit Changed."""
        prefix = f"field-{self._section}-"
        if not field_id.startswith(prefix):
            return
        # Restore dotted keys from "__"-encoded widget ids.
        key = field_id[len(prefix):].replace("__", ".")

        field_def = next((f for f in self._fields if f["key"] == key), None)
        if field_def is None:
            return

        try:
            value = self._coerce(raw_value, field_def)
        except (ValueError, TypeError):
            return  # Ignore invalid input until user fixes it

        if value == self._get_nested(key):
            # Select/Switch/Input widgets fire a Changed event when they are
            # first mounted with their initial value (a Textual quirk) —
            # that is not a real user edit, so don't mark the form dirty.
            return

        self._set_nested(key, value)
        self.post_message(self.Changed(self._section, dict(self._values)))

    def _get_nested(self, key: str) -> Any:
        """Read a flat or one-level dotted key from the section dict."""
        if "." not in key:
            return self._values.get(key, "")
        parent, child = key.split(".", 1)
        nested = self._values.get(parent)
        if not isinstance(nested, dict):
            return ""
        return nested.get(child, "")

    def _set_nested(self, key: str, value: Any) -> None:
        """Write a flat or one-level dotted key without wiping siblings."""
        if "." not in key:
            self._values[key] = value
            return
        parent, child = key.split(".", 1)
        nested = self._values.get(parent)
        if not isinstance(nested, dict):
            nested = {}
            self._values[parent] = nested
        else:
            # Copy so we do not mutate a shared raw-config reference unexpectedly.
            nested = dict(nested)
            self._values[parent] = nested
        nested[child] = value

    def _coerce(self, raw: Any, field_def: dict) -> Any:
        ftype = field_def["type"]
        if ftype == "bool":
            return bool(raw)
        if ftype == "int":
            return int(raw)
        if ftype == "float":
            return float(raw)
        return str(raw)

    def get_values(self) -> dict[str, Any]:
        """Return the current field values."""
        return dict(self._values)

    @staticmethod
    def _select_options(raw_options: list[Any]) -> list[tuple[str, str]]:
        """Normalize select options as (label, value) pairs."""
        options: list[tuple[str, str]] = []
        for opt in raw_options:
            if isinstance(opt, (list, tuple)) and len(opt) == 2:
                options.append((str(opt[0]), str(opt[1])))
            else:
                options.append((str(opt), str(opt)))
        return options
