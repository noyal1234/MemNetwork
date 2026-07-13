"""Config Editor screen — form-based editing of .brain/config.json."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Static
from textual.worker import Worker

from brainkm.tui.widgets.config_form import SECTION_FIELDS, ConfigForm


class ConfigEditorScreen(Screen):
    """Phase 2 — form-based config editing with Pydantic validation."""

    BINDINGS = [
        ("d", "switch_dashboard", "Dashboard"),
        ("a", "switch_actions", "Actions"),
        ("w", "switch_wizard", "Wizard"),
        ("escape", "switch_dashboard", "Back"),
    ]

    def __init__(self, project_dir: Path | None = None) -> None:
        super().__init__()
        self._project_dir = project_dir
        self._config_dict: dict[str, Any] = {}
        self._dirty = False
        self._validation_error: str | None = None
        self._api_key_dirty = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="config-container"):
            yield Static(
                "⚙  Config Editor — .brain/config.json",
                classes="panel-title",
            )
            yield Static(
                "Edit settings below. Changes are validated live via BrainConfig.",
                classes="field-help",
            )
            # Placeholder — forms are mounted dynamically on_mount
            yield Vertical(id="config-forms")

            # --- API Key section (separate — writes to .env) ---
            with Vertical(classes="config-section"):
                yield Static("🔑 Groq API Key", classes="section-title")
                yield Static(
                    "Stored in project .env file, never in config.json or brain.db",
                    classes="field-help",
                )
                yield Static("Loading…", id="groq-api-key-status", classes="api-key-status")
                with Horizontal(classes="config-field-row"):
                    yield Label("New key:", classes="field-label")
                    yield Input(
                        placeholder="gsk_… (leave blank to keep current)",
                        password=True,
                        id="field-groq-api-key",
                    )

            # --- Validation status ---
            yield Static("", id="validation-status")

        # --- Bottom buttons ---
        with Horizontal(id="config-buttons"):
            yield Button("💾 Save", id="btn-save", classes="-primary", disabled=True)
            yield Button("↩  Discard", id="btn-discard")
            yield Button("← Dashboard", id="btn-back")
        yield Footer()

    def on_mount(self) -> None:
        """Load config and render forms."""
        self._load_config()

    @work(thread=True, group="config-load", exit_on_error=False)
    def _load_config(self) -> dict[str, Any]:
        try:
            from brainkm.services.config_loader import config_path, load_brain_config

            cfg = load_brain_config(self._project_dir)
            cfg_dict = cfg.model_dump()
            # Also load the raw JSON for round-tripping unknown fields
            cp = config_path(self._project_dir)
            if cp.is_file():
                raw = json.loads(cp.read_text(encoding="utf-8"))
            else:
                raw = cfg_dict
            return {"parsed": cfg_dict, "raw": raw, "path": str(cp)}
        except Exception as exc:
            return {"error": str(exc)}

    def _on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        from textual.worker import WorkerState

        if event.state != WorkerState.SUCCESS:
            return
        worker = event.worker
        if worker.group == "config-load":
            # DOM updates must run on the main loop. Textual 8's
            # remove_children()/mount() return AwaitRemove/AwaitMount —
            # calling them without await leaves stale widgets in the ID
            # registry and raises DuplicateIds on the next load.
            self.run_worker(
                self._apply_loaded_config(worker.result),
                group="config-render",
                exclusive=True,
                exit_on_error=False,
            )

    async def _apply_loaded_config(self, result: dict) -> None:
        if result.get("error"):
            status = self.query_one("#validation-status", Static)
            status.update(f"Error loading config: {result['error']}")
            status.set_classes("validation-error")
            return

        self._config_dict = result["parsed"]
        self._raw_config = result.get("raw", {})
        forms_container = self.query_one("#config-forms", Vertical)
        await forms_container.remove_children()

        forms: list[ConfigForm] = []
        for section_name in SECTION_FIELDS:
            section_data = self._config_dict.get(section_name, {})
            if isinstance(section_data, dict):
                forms.append(
                    ConfigForm(
                        section_name,
                        section_data,
                        id=f"form-{section_name}",
                    )
                )

        if forms:
            await forms_container.mount(*forms)

        self._dirty = False
        self._validation_error = None
        status = self.query_one("#validation-status", Static)
        status.update("")
        self._update_save_button()
        self._update_api_key_status()

    def _update_api_key_status(self) -> None:
        """Show the currently configured (masked) Groq API key."""
        from brainkm.services.groq_advisor import build_groq_report

        status = self.query_one("#groq-api-key-status", Static)
        try:
            report = build_groq_report(project_dir=self._project_dir)
            if report.api_key_present and report.api_key_masked:
                status.update(f"Current key: {report.api_key_masked}")
                status.set_classes("api-key-status value--ok")
            else:
                status.update("Current key: not set")
                status.set_classes("api-key-status value--warning")
        except Exception as exc:
            status.update(f"Current key: unknown ({exc})")
            status.set_classes("api-key-status value--muted")

    def on_config_form_changed(self, event: ConfigForm.Changed) -> None:
        """A config field was edited — update our dict and validate."""
        self._config_dict[event.section] = event.data
        self._dirty = True
        self._validate_config()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Track edits to the Groq API key input, which lives outside any
        ConfigForm and therefore isn't covered by on_config_form_changed.
        Without this, entering *only* an API key (no other config edit)
        would leave Save permanently disabled.
        """
        if event.input.id == "field-groq-api-key":
            self._api_key_dirty = bool(event.value.strip())
            self._update_save_button()

    def _validate_config(self) -> None:
        """Run Pydantic validation on the merged config."""
        from brainkm.models.brain_config import BrainConfig

        try:
            merged = dict(self._raw_config)
            # Overlay edited sections
            for section in SECTION_FIELDS:
                if section in self._config_dict:
                    merged[section] = self._config_dict[section]
            BrainConfig.model_validate(merged)
            self._validation_error = None
            status = self.query_one("#validation-status", Static)
            status.update("✓ Configuration is valid")
            status.set_classes("validation-ok")
        except ValidationError as exc:
            self._validation_error = str(exc)
            status = self.query_one("#validation-status", Static)
            # Show first error only for brevity
            first_err = exc.errors()[0] if exc.errors() else {}
            loc = " → ".join(str(part) for part in first_err.get("loc", []))
            msg = first_err.get("msg", str(exc))
            status.update(f"✗ Validation error: {loc}: {msg}")
            status.set_classes("validation-error")

        self._update_save_button()

    def _update_save_button(self) -> None:
        btn = self.query_one("#btn-save", Button)
        btn.disabled = (
            not (self._dirty or self._api_key_dirty)
            or self._validation_error is not None
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-save":
            self._save_config()
        elif event.button.id == "btn-discard":
            self._load_config()
            self._dirty = False
            self._api_key_dirty = False
            self.query_one("#field-groq-api-key", Input).value = ""
            self._update_save_button()
        elif event.button.id == "btn-back":
            self.action_switch_dashboard()

    def _save_config(self) -> None:
        """Atomically write the validated config to .brain/config.json."""
        from brainkm.models.brain_config import BrainConfig
        from brainkm.services.config_loader import config_path

        merged = dict(self._raw_config)
        for section in SECTION_FIELDS:
            if section in self._config_dict:
                merged[section] = self._config_dict[section]

        # Final validation gate
        try:
            validated = BrainConfig.model_validate(merged)
        except ValidationError as exc:
            self.notify(f"Cannot save: {exc}", severity="error")
            return

        cfg_path = config_path(self._project_dir)
        output = validated.model_dump(mode="json")

        # Atomic write: temp file → os.replace
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(cfg_path.parent),
                suffix=".json.tmp",
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=2)
                f.write("\n")
            os.replace(tmp_path, str(cfg_path))
            self._raw_config = output
            self._dirty = False
            self._api_key_dirty = False
            self._update_save_button()
            self.notify("✓ Config saved", severity="information")
        except Exception as exc:
            self.notify(f"Save failed: {exc}", severity="error")

        # Also handle Groq API key → .env
        self._save_api_key()

    def _save_api_key(self) -> None:
        """Write GROQ_API_KEY to project .env if the user entered one."""
        try:
            api_key_input = self.query_one("#field-groq-api-key", Input)
        except Exception:
            return
        api_key = api_key_input.value.strip()
        if not api_key:
            return

        project = self._project_dir or Path.cwd()
        env_path = project / ".env"

        # Read existing .env lines, replace or append GROQ_API_KEY
        lines: list[str] = []
        found = False
        if env_path.is_file():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("GROQ_API_KEY="):
                    lines.append(f"GROQ_API_KEY={api_key}")
                    found = True
                else:
                    lines.append(line)
        if not found:
            lines.append(f"GROQ_API_KEY={api_key}")

        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        api_key_input.value = ""
        self._api_key_dirty = False
        self._update_api_key_status()
        self._update_save_button()
        self.notify("✓ GROQ_API_KEY written to .env", severity="information")

    # ------------------------------------------------------------------
    # Screen switching
    # ------------------------------------------------------------------

    def action_switch_dashboard(self) -> None:
        self.app.switch_screen("dashboard")

    def action_switch_actions(self) -> None:
        self.app.switch_screen("actions")

    def action_switch_wizard(self) -> None:
        self.app.switch_screen("wizard")
