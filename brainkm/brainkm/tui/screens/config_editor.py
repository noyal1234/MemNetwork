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
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Static
from textual.worker import Worker, WorkerState

from brainkm.tui.theme import bracket_label, escape_markup
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
        self._raw_config: dict[str, Any] = {}
        self._dirty = False
        self._validation_error: str | None = None
        self._api_key_dirty = False

    @property
    def is_dirty(self) -> bool:
        """True when config forms or the Groq key field have unsaved edits."""
        return bool(self._dirty or self._api_key_dirty)

    def mark_clean(self) -> None:
        """Clear dirty flags (used after discard confirm before leaving)."""
        self._dirty = False
        self._api_key_dirty = False

    def compose(self) -> ComposeResult:
        yield Header()
        # Layout column (not dock): scroll (1fr) + Save row above Footer.
        # dock:bottom on #config-buttons fights Footer and clips Save on short terminals.
        with Vertical(id="config-layout"):
            with VerticalScroll(id="config-container"):
                yield Static(
                    escape_markup("[ CONFIG ]"),
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
                    yield Static(
                        escape_markup("[ GROQ API KEY ]"),
                        classes="section-title",
                    )
                    yield Static(
                        "Stored in project .env file, never in config.json or brain.db",
                        classes="field-help",
                    )
                    yield Static(
                        "Loading…",
                        id="groq-api-key-status",
                        classes="api-key-status",
                    )
                    with Horizontal(classes="config-field-row"):
                        yield Label("New key:", classes="field-label")
                        yield Input(
                            placeholder="gsk_… (leave blank to keep current)",
                            password=True,
                            id="field-groq-api-key",
                        )

                # --- Validation status ---
                yield Static("", id="validation-status")

            with Horizontal(id="config-buttons"):
                yield Button(
                    bracket_label("Save"),
                    id="btn-save",
                    classes="-primary",
                    disabled=True,
                )
                yield Button(bracket_label("Discard"), id="btn-discard")
                yield Button(bracket_label("Dashboard"), id="btn-back")
        yield Footer()

    def on_mount(self) -> None:
        """Load config and render forms."""
        self._load_config()

    @work(thread=True, group="config-load", exit_on_error=False)
    def _load_config(self) -> dict[str, Any]:
        try:
            from brainkm.services.config_loader import (
                config_path,
                load_brain_config,
                raw_config_has_commit_trace,
            )

            cfg = load_brain_config(self._project_dir)
            cfg_dict = cfg.model_dump()
            # Also load the raw JSON for round-tripping unknown fields
            cp = config_path(self._project_dir)
            if cp.is_file():
                raw = json.loads(cp.read_text(encoding="utf-8"))
                # Grandfather: missing key displays as Off (do not imply schema default).
                if not raw_config_has_commit_trace(self._project_dir):
                    git = dict(cfg_dict.get("git") or {})
                    git["commit_trace"] = False
                    cfg_dict["git"] = git
            else:
                raw = cfg_dict
            return {"parsed": cfg_dict, "raw": raw, "path": str(cp)}
        except Exception as exc:
            return {"error": str(exc)}

    def _on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.ERROR:
            err = escape_markup(str(event.worker.error or "unknown"))
            group = event.worker.group or ""
            if group == "config-save":
                self.notify(f"Save failed: {err}", severity="error")
            elif group == "api-key-status":
                try:
                    status = self.query_one("#groq-api-key-status", Static)
                    status.update(f"Current key: unknown ({err})")
                    status.set_classes("api-key-status value--muted")
                except Exception:
                    pass
            elif group == "config-load":
                self.notify(f"Config load failed: {err}", severity="error")
            return
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
        elif worker.group == "distill-status":
            self._apply_distill_status(worker.result)
        elif worker.group == "api-key-status":
            self._apply_api_key_status(worker.result)
        elif worker.group == "config-save":
            self._apply_save_result(worker.result)

    def _apply_distill_status(self, result: dict[str, Any]) -> None:
        try:
            line = self.query_one("#distill-status-line", Static)
        except Exception:
            return
        if result.get("error"):
            line.update(escape_markup(f"Distill readiness: unknown ({result['error']})"))
            return
        line.update(escape_markup(result.get("line", "Distill readiness: unknown")))

    def _apply_api_key_status(self, result: dict[str, Any]) -> None:
        status = self.query_one("#groq-api-key-status", Static)
        if result.get("error"):
            status.update(escape_markup(f"Current key: unknown ({result['error']})"))
            status.set_classes("api-key-status value--muted")
            return
        if result.get("present") and result.get("masked"):
            status.update(f"Current key: {result['masked']}")
            status.set_classes("api-key-status value--ok")
        else:
            status.update("Current key: not set")
            status.set_classes("api-key-status value--warning")

    def _apply_save_result(self, result: dict[str, Any]) -> None:
        if result.get("error"):
            self.notify(escape_markup(f"Save failed: {result['error']}"), severity="error")
            return
        if result.get("config_saved"):
            self._raw_config = result.get("raw") or self._raw_config
            self._dirty = False
            self.notify("✓ Config saved", severity="information")
        for warn in result.get("commit_trace_warnings") or []:
            self.notify(escape_markup(str(warn)), severity="warning")
        if result.get("commit_trace_hook_error"):
            self.notify(
                escape_markup(f"Commit-trace hook: {result['commit_trace_hook_error']}"),
                severity="warning",
            )
        if result.get("api_key_saved"):
            self._api_key_dirty = False
            try:
                self.query_one("#field-groq-api-key", Input).value = ""
            except Exception:
                pass
            self.notify("✓ GROQ_API_KEY written to .env", severity="information")
            self._update_api_key_status()
        self._update_save_button()

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

        forms: list[Any] = []
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
            if section_name == "capture":
                forms.append(
                    Static(
                        "Distill readiness: loading…",
                        id="distill-status-line",
                        classes="field-help",
                    )
                )

        if forms:
            await forms_container.mount(*forms)

        self._dirty = False
        self._api_key_dirty = False
        self._validation_error = None
        status = self.query_one("#validation-status", Static)
        status.update("")
        self._update_save_button()
        self._update_api_key_status()
        self._load_distill_status()

    def _update_api_key_status(self) -> None:
        """Kick off a threaded Groq key probe (never blocks the UI)."""
        try:
            status = self.query_one("#groq-api-key-status", Static)
            status.update("Current key: Checking…")
            status.set_classes("api-key-status value--muted")
        except Exception:
            pass
        self._do_api_key_status()

    @work(thread=True, group="api-key-status", exclusive=True, exit_on_error=False)
    def _do_api_key_status(self) -> dict[str, Any]:
        from brainkm.services.groq_advisor import build_groq_report

        try:
            report = build_groq_report(project_dir=self._project_dir)
            return {
                "present": report.api_key_present,
                "masked": report.api_key_masked or "",
            }
        except Exception as exc:
            return {"error": str(exc)}

    def on_config_form_changed(self, event: ConfigForm.Changed) -> None:
        """A config field was edited — update our dict and validate."""
        self._config_dict[event.section] = event.data
        self._dirty = True
        self._validate_config()
        if event.section == "capture":
            self._load_distill_status()

    def _load_distill_status(self) -> None:
        """Refresh the capture-section distill readiness line."""
        self._do_load_distill_status()

    @work(thread=True, group="distill-status", exclusive=True, exit_on_error=False)
    def _do_load_distill_status(self) -> dict[str, Any]:
        from brainkm.services.distill_status import (
            build_distill_status,
            format_distill_status_line,
        )

        try:
            statuses = build_distill_status(project_dir=self._project_dir)
            return {"line": f"Distill readiness: {format_distill_status_line(statuses)}"}
        except Exception as exc:
            return {"error": str(exc)}

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
            status.update(escape_markup(f"✗ Validation error: {loc}: {msg}"))
            status.set_classes("validation-error")

        self._update_save_button()

    def _update_save_button(self) -> None:
        btn = self.query_one("#btn-save", Button)
        btn.disabled = (
            not (self._dirty or self._api_key_dirty) or self._validation_error is not None
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
        """Validate on the UI thread, then write config/.env in a worker."""
        from brainkm.models.brain_config import BrainConfig

        merged = dict(self._raw_config)
        for section in SECTION_FIELDS:
            if section in self._config_dict:
                merged[section] = self._config_dict[section]

        try:
            validated = BrainConfig.model_validate(merged)
        except ValidationError as exc:
            self.notify(escape_markup(f"Cannot save: {exc}"), severity="error")
            return

        output = validated.model_dump(mode="json")
        # Keep groq mode and cloud consent in lockstep (Config Editor parity with wizard).
        capture = output.get("capture")
        if isinstance(capture, dict) and capture.get("distill_mode") == "groq":
            capture["cloud_distill_acknowledged"] = True
        try:
            api_key = self.query_one("#field-groq-api-key", Input).value.strip()
        except Exception:
            api_key = ""

        self.notify("Saving…", severity="information")
        self._do_save(output, api_key)

    @work(thread=True, group="config-save", exclusive=True, exit_on_error=False)
    def _do_save(self, output: dict[str, Any], api_key: str) -> dict[str, Any]:
        from brainkm.services.config_loader import config_path

        result: dict[str, Any] = {"config_saved": False, "api_key_saved": False}
        try:
            cfg_path = config_path(self._project_dir)
            fd, tmp_path = tempfile.mkstemp(
                dir=str(cfg_path.parent),
                suffix=".json.tmp",
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=2)
                f.write("\n")
            os.replace(tmp_path, str(cfg_path))
            result["config_saved"] = True
            result["raw"] = output
        except Exception as exc:
            return {"error": str(exc)}

        from brainkm.services.install import resolve_hook_command, resolve_project_dir

        root = resolve_project_dir(self._project_dir)

        if api_key:
            try:
                env_path = root / ".env"
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
                try:
                    env_path.chmod(0o600)
                except OSError:
                    pass
                result["api_key_saved"] = True
            except Exception as exc:
                return {
                    **result,
                    "error": f"Config saved but .env write failed: {exc}",
                }

        # Keep post-commit hook in sync with explicit git.commit_trace.
        try:
            from brainkm.models.brain_config import BrainConfig
            from brainkm.services.config_loader import should_install_commit_hook
            from brainkm.services.git_note import (
                install_post_commit_hook,
                uninstall_post_commit_hook,
            )
            validated = BrainConfig.model_validate(output)
            if should_install_commit_hook(root, validated):
                hook_result = install_post_commit_hook(
                    root,
                    brainkm_bin=resolve_hook_command(dev=True),
                )
                result["commit_trace_hook"] = str(hook_result.path) if hook_result.path else None
                result["commit_trace_warnings"] = list(hook_result.warnings)
            else:
                result["commit_trace_hook_removed"] = uninstall_post_commit_hook(root)
        except Exception as exc:
            result["commit_trace_hook_error"] = str(exc)

        return result

    # ------------------------------------------------------------------
    # Screen switching
    # ------------------------------------------------------------------

    def action_switch_dashboard(self) -> None:
        self.app.switch_screen("dashboard")

    def action_switch_actions(self) -> None:
        self.app.switch_screen("actions")

    def action_switch_wizard(self) -> None:
        self.app.switch_screen("wizard")
