"""Wizard screen — guided first-run setup for brainkm."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    RadioButton,
    RadioSet,
    Static,
)
from textual.worker import Worker, WorkerState

from brainkm.services.distill_status import DISTILL_MODE_LABELS, PRIMARY_DISTILL_MODES
from brainkm.tui.theme import border_color_pair, bracket_label, escape_markup
from brainkm.tui.widgets.rich_log_panel import RichLogPanel

# ---------------------------------------------------------------------------
# Wizard step IDs
# ---------------------------------------------------------------------------
STEP_PROJECT = "step-project"
STEP_INSTALL = "step-install"
STEP_DOCTOR = "step-doctor"
STEP_DISTILL = "step-distill"
STEP_CURSOR_CLI = "step-cursor-cli"
STEP_APIKEY = "step-apikey"
STEP_GRAPH = "step-graph"
STEP_DONE = "step-done"

STEPS = [
    STEP_PROJECT,
    STEP_INSTALL,
    STEP_DOCTOR,
    STEP_DISTILL,
    STEP_CURSOR_CLI,
    STEP_APIKEY,
    STEP_GRAPH,
    STEP_DONE,
]


class WizardScreen(Screen):
    """Phase 4 — guided first-run wizard.

    Walks through: project dir → install → hardware doctor → distill mode
    → Cursor agent CLI (optional) → API key → graph sync → done.
    """

    BINDINGS = [
        ("d", "switch_dashboard", "Dashboard"),
        ("escape", "switch_dashboard", "Back"),
    ]

    def __init__(self, project_dir: Path | None = None) -> None:
        super().__init__()
        self._project_dir = project_dir or Path.cwd()
        self._current_step = 0
        self._distill_mode = "cursor"

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="wizard-container"):
            yield Static(
                escape_markup("[ WIZARD ]"),
                classes="panel-title",
            )
            yield Static(
                "Set up your project brain step by step",
                classes="value--muted",
            )

            # --- Step 1: Project directory ---
            with Vertical(classes="wizard-step", id=STEP_PROJECT):
                yield Static("1 ─ Project Directory", classes="step-title")
                yield Static(
                    f"Project: [bold]{escape_markup(str(self._project_dir))}[/]",
                    id="wizard-project-path",
                )
                yield Static("", id="wizard-project-status")

            # --- Step 2: Install scaffolding ---
            with Vertical(classes="wizard-step", id=STEP_INSTALL):
                yield Static("2 ─ Install Scaffolding", classes="step-title")
                yield Static(
                    "Creates .brain/ directory, config.json, MCP config, and Cursor hooks.",
                    classes="step-description",
                )
                yield Static("", id="wizard-install-status")

            # --- Step 3: Hardware doctor ---
            with Vertical(classes="wizard-step", id=STEP_DOCTOR):
                yield Static("3 ─ Hardware Doctor", classes="step-title")
                yield Static(
                    "Detect hardware capabilities and recommend an Ollama model.",
                    classes="step-description",
                )
                yield Static("", id="wizard-doctor-status")

            # --- Step 4: Distill mode ---
            with Vertical(classes="wizard-step", id=STEP_DISTILL):
                yield Static("4 ─ Distill Mode", classes="step-title")
                yield Static(
                    "How should brainkm extract neurons from transcripts?\n"
                    "Pick one backend. Cursor Agent CLI (next step) is only an "
                    "optional upgrade for cursor mode — not a separate mode.",
                    classes="step-description",
                )
                with RadioSet(id="wizard-distill-radio"):
                    yield RadioButton(
                        DISTILL_MODE_LABELS["cursor"],
                        value=True,
                        id="radio-distill-cursor",
                    )
                    yield RadioButton(
                        DISTILL_MODE_LABELS["ollama"],
                        id="radio-distill-ollama",
                    )
                    yield RadioButton(
                        DISTILL_MODE_LABELS["groq"],
                        id="radio-distill-groq",
                    )
                yield Static("", id="wizard-distill-status")

            # --- Step 5: Optional Cursor Agent CLI upgrade (not a distill mode) ---
            with Vertical(classes="wizard-step", id=STEP_CURSOR_CLI):
                yield Static(
                    "5 ─ Upgrade Cursor Distill (Agent CLI, Optional)",
                    classes="step-title",
                )
                yield Static(
                    "Not a separate distill mode. Only upgrades cursor mode: "
                    "heuristic Cursor distill already works without this. "
                    "Install the agent CLI for optional LLM-quality extraction.",
                    id="wizard-cursor-cli-description",
                    classes="step-description",
                )
                yield Static(
                    "1. Install: curl https://cursor.com/install -fsS | bash\n"
                    "2. PATH: ensure ~/.local/bin is on PATH\n"
                    "3. Verify: which agent  ·  brainkm cursor doctor",
                    id="wizard-cursor-cli-checklist",
                    classes="step-description",
                )
                yield Static("", id="wizard-cursor-cli-status")

            # --- Step 6: API key ---
            with Vertical(classes="wizard-step", id=STEP_APIKEY):
                yield Static("6 ─ API Key (Optional)", classes="step-title")
                yield Static(
                    "If you chose 'groq', paste your GROQ_API_KEY below.",
                    classes="step-description",
                )
                with Horizontal(classes="config-field"):
                    yield Label("GROQ_API_KEY:")
                    yield Input(
                        placeholder="gsk_...",
                        password=True,
                        id="wizard-groq-key",
                    )
                yield Static("", id="wizard-apikey-status")

            # --- Step 7: Graph sync ---
            with Vertical(classes="wizard-step", id=STEP_GRAPH):
                yield Static("7 ─ Graph Sync (Optional)", classes="step-title")
                yield Static(
                    "Run Graphify AST extraction and import into brain.db.",
                    classes="step-description",
                )
                yield Static("", id="wizard-graph-status")

            # --- Step 8: Done ---
            with Vertical(classes="wizard-step", id=STEP_DONE):
                yield Static("✓ Setup Complete!", classes="step-title")
                yield Static(
                    "Your project brain is ready. Switch to the Dashboard to see the status.",
                    classes="step-description",
                )

            # --- Log panel ---
            yield RichLogPanel(title="[ WIZARD LOG ]", id="wizard-log")

            # --- Navigation buttons (inside container so Footer doesn't cover them) ---
            with Horizontal(id="wizard-nav"):
                yield Button(bracket_label("Back"), id="btn-wizard-back", disabled=True)
                yield Button(bracket_label("Run Step"), id="btn-wizard-run", classes="-primary")
                yield Button(bracket_label("Skip"), id="btn-wizard-skip")
                yield Button(
                    bracket_label("Dashboard"), id="btn-wizard-finish", disabled=True
                )
        yield Footer()

    @property
    def log_panel(self) -> RichLogPanel:
        return self.query_one("#wizard-log", RichLogPanel)

    def on_mount(self) -> None:
        self._update_step_visibility()
        self._check_project()
        self._annotate_distill_radios()

    # ------------------------------------------------------------------
    # Step management
    # ------------------------------------------------------------------

    def _update_step_visibility(self) -> None:
        """Show only the active step; hide the rest."""
        for i, step_id in enumerate(STEPS):
            try:
                step = self.query_one(f"#{step_id}")
            except Exception:
                continue
            if i == self._current_step:
                step.display = True
                step.styles.opacity = 1.0
                active, _inactive = border_color_pair()
                step.styles.border = ("solid", active)
            else:
                step.display = False
                step.styles.opacity = 1.0
                _active, inactive = border_color_pair()
                step.styles.border = ("solid", inactive)

        # Update nav buttons
        back_btn = self.query_one("#btn-wizard-back", Button)
        run_btn = self.query_one("#btn-wizard-run", Button)
        skip_btn = self.query_one("#btn-wizard-skip", Button)
        finish_btn = self.query_one("#btn-wizard-finish", Button)

        back_btn.disabled = self._current_step == 0
        is_done = self._current_step >= len(STEPS) - 1
        run_btn.disabled = is_done
        skip_btn.disabled = is_done
        finish_btn.disabled = not is_done

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id == "btn-wizard-back":
            self._go_back()
        elif btn_id == "btn-wizard-run":
            self._run_current_step()
        elif btn_id == "btn-wizard-skip":
            self._skip_current_step()
        elif btn_id == "btn-wizard-finish":
            self.action_switch_dashboard()

    def _skip_current_step(self) -> None:
        step = STEPS[self._current_step]
        if step == STEP_CURSOR_CLI:
            self.log_panel.log_info(
                "Skipped Cursor agent CLI — heuristic distill remains available"
            )
            try:
                status = self.query_one("#wizard-cursor-cli-status", Static)
                status.update(
                    "[dim]● Skipped — heuristic Cursor distill still works[/]"
                )
            except Exception:
                pass
        self._advance()

    def _advance(self) -> None:
        if self._current_step < len(STEPS) - 1:
            self._current_step += 1
            self._update_step_visibility()

    def _go_back(self) -> None:
        if self._current_step > 0:
            self._current_step -= 1
            self._update_step_visibility()

    def _run_current_step(self) -> None:
        step = STEPS[self._current_step]
        runners = {
            STEP_PROJECT: self._check_project,
            STEP_INSTALL: self._run_install,
            STEP_DOCTOR: self._run_doctor,
            STEP_DISTILL: self._apply_distill_mode,
            STEP_CURSOR_CLI: self._run_cursor_cli,
            STEP_APIKEY: self._apply_api_key,
            STEP_GRAPH: self._run_graph_sync,
        }
        runner = runners.get(step)
        if runner:
            runner()

    # ------------------------------------------------------------------
    # Step implementations
    # ------------------------------------------------------------------

    def _check_project(self) -> None:
        """Step 1: Check if .brain/ exists."""
        brain_dir = self._project_dir / ".brain"
        status = self.query_one("#wizard-project-status", Static)
        if brain_dir.is_dir():
            status.update(
                "[bold yellow]● .brain/ already exists — will update existing config[/]"
            )
            self.log_panel.log_warning(".brain/ directory found — will update, not overwrite")
        else:
            status.update("[dim]● .brain/ will be created[/]")
            self.log_panel.log_info(f"Project directory: {self._project_dir}")
        self._advance()

    def _run_install(self) -> None:
        self.log_panel.log_info("Running brainkm install…")
        self._do_install()

    @work(thread=True, group="wizard", exit_on_error=False)
    def _do_install(self) -> dict[str, Any]:
        from brainkm.services.install import run_install

        result = run_install(project_dir=self._project_dir, dev=True, force=False, no_graph=True)
        return {
            "step": STEP_INSTALL,
            "project_dir": str(result.project_dir),
            "files_written": [str(p) for p in result.files_written],
            "files_skipped": [str(p) for p in result.files_skipped],
            "warnings": list(result.warnings),
        }

    def _run_doctor(self) -> None:
        self.log_panel.log_info("Running hardware doctor…")
        self._do_doctor()

    @work(thread=True, group="wizard", exit_on_error=False)
    def _do_doctor(self) -> dict[str, Any]:
        try:
            from brainkm.services.ollama_advisor import build_doctor_report, format_doctor_report

            report = build_doctor_report(project_dir=self._project_dir)
            return {
                "step": STEP_DOCTOR,
                "formatted": format_doctor_report(report),
                "recommended": report.recommendation.model,
                "reachable": report.ollama.reachable,
            }
        except Exception as exc:
            return {"step": STEP_DOCTOR, "error": str(exc)}

    def _annotate_distill_radios(self) -> None:
        """Probe backends and annotate distill radio labels with readiness."""
        self._do_annotate_distill_radios()

    @work(thread=True, group="wizard-annotate", exclusive=True, exit_on_error=False)
    def _do_annotate_distill_radios(self) -> dict[str, Any]:
        from brainkm.services.distill_status import (
            build_distill_status,
            format_distill_status_line,
        )

        try:
            statuses = build_distill_status(project_dir=self._project_dir)
            return {
                "step": "annotate-distill",
                "by_mode": {s.mode: {"ready": s.ready, "detail": s.detail} for s in statuses},
                "line": format_distill_status_line(statuses),
            }
        except Exception as exc:
            return {"step": "annotate-distill", "error": str(exc)}

    def _apply_distill_mode(self) -> None:
        """Step 4: Read radio selection and write to config."""
        # Primary picker only: cursor / ollama / groq (rules is advanced, not listed).
        mode_map = {i: mode for i, mode in enumerate(PRIMARY_DISTILL_MODES)}
        try:
            radio_set = self.query_one("#wizard-distill-radio", RadioSet)
            idx = radio_set.pressed_index
            self._distill_mode = mode_map.get(idx, "cursor")
        except Exception:
            self._distill_mode = "cursor"

        self.log_panel.log_info(f"Selected distill mode: {self._distill_mode}")
        self._do_apply_distill()

    def _run_cursor_cli(self) -> None:
        """Step 5: Optional Agent CLI upgrade for cursor mode only."""
        try:
            desc = self.query_one("#wizard-cursor-cli-description", Static)
            if self._distill_mode == "cursor":
                desc.update(
                    "Not a separate distill mode. Only upgrades cursor mode: "
                    "heuristic Cursor distill already works without this. "
                    "Install the agent CLI for optional LLM-quality extraction."
                )
            else:
                desc.update(
                    "Skipped for non-cursor modes — Agent CLI only upgrades "
                    f"distill_mode=cursor (current: {self._distill_mode})."
                )
        except Exception:
            pass
        if self._distill_mode != "cursor":
            self.log_panel.log_info(
                "Skipping Agent CLI — only relevant when distill mode is cursor"
            )
            self._advance()
            return
        self.log_panel.log_info("Checking Cursor agent CLI…")
        self._do_cursor_cli()

    @work(thread=True, group="wizard", exit_on_error=False)
    def _do_cursor_cli(self) -> dict[str, Any]:
        from brainkm.services.cursor_advisor import (
            build_cursor_doctor_report,
            ensure_cursor_agent_path,
            format_cursor_report,
            install_cursor_agent_cli,
            probe_cursor_agent,
        )

        try:
            ensure_cursor_agent_path()
            status = probe_cursor_agent()
            installed = False
            install_error: str | None = None
            if not status.found:
                install_result = install_cursor_agent_cli()
                installed = True
                install_error = install_result.error
                status = probe_cursor_agent()
            report = build_cursor_doctor_report(project_dir=self._project_dir)
            return {
                "step": STEP_CURSOR_CLI,
                "found": status.found,
                "bin_path": status.bin_path,
                "installed": installed,
                "install_error": install_error,
                "formatted": format_cursor_report(report),
            }
        except Exception as exc:
            return {"step": STEP_CURSOR_CLI, "error": str(exc)}

    @work(thread=True, group="wizard", exit_on_error=False)
    def _do_apply_distill(self) -> dict[str, Any]:
        import json

        from brainkm.services.config_loader import config_path

        cp = config_path(self._project_dir)
        if cp.is_file():
            cfg = json.loads(cp.read_text(encoding="utf-8"))
        else:
            cfg = {}
        cfg.setdefault("capture", {})["distill_mode"] = self._distill_mode
        cp.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        return {"step": STEP_DISTILL, "mode": self._distill_mode}

    def _apply_api_key(self) -> None:
        """Step 5: Write GROQ_API_KEY to .env."""
        try:
            key_input = self.query_one("#wizard-groq-key", Input)
        except Exception:
            self._advance()
            return
        api_key = key_input.value.strip()
        if not api_key:
            self.log_panel.log_info("No API key provided — skipping")
            self._advance()
            return
        self.log_panel.log_info("Writing GROQ_API_KEY to .env…")
        self._do_apply_api_key(api_key)

    @work(thread=True, group="wizard", exit_on_error=False)
    def _do_apply_api_key(self, api_key: str) -> dict[str, Any]:
        env_path = self._project_dir / ".env"
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

        # Verify
        try:
            from brainkm.services.groq_advisor import build_groq_report

            report = build_groq_report(project_dir=self._project_dir)
            return {
                "step": STEP_APIKEY,
                "reachable": report.status.reachable,
                "masked": report.api_key_masked,
            }
        except Exception as exc:
            return {"step": STEP_APIKEY, "error": str(exc)}

    def _run_graph_sync(self) -> None:
        self.log_panel.log_info("Starting graph sync…")
        self._do_graph_sync()

    @work(thread=True, group="wizard", exit_on_error=False)
    def _do_graph_sync(self) -> dict[str, Any]:
        try:
            from brainkm.services.config_loader import load_brain_config
            from brainkm.services.graphify_sync import sync_graph

            cfg = load_brain_config(self._project_dir)
            result = sync_graph(
                project_dir=self._project_dir,
                config=cfg,
                extract=True,
            )
            return {
                "step": STEP_GRAPH,
                "status": result.status,
                "message": result.message,
                "node_count": result.import_result.node_count if result.import_result else 0,
            }
        except Exception as exc:
            return {"step": STEP_GRAPH, "error": str(exc)}

    # ------------------------------------------------------------------
    # Worker result handler
    # ------------------------------------------------------------------

    def _on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.ERROR:
            if event.worker.group == "wizard":
                self.log_panel.log_error(f"Step failed: {event.worker.error}")
            return
        if event.state != WorkerState.SUCCESS:
            return
        if event.worker.group == "wizard-annotate":
            self._handle_annotate_result(event.worker.result)
            return
        if event.worker.group == "wizard":
            self._handle_wizard_result(event.worker.result)

    def _handle_annotate_result(self, result: dict[str, Any]) -> None:
        if result.get("error"):
            try:
                status = self.query_one("#wizard-distill-status", Static)
                status.update(
                    f"[dim]Readiness probe failed: {escape_markup(str(result['error']))}[/]"
                )
            except Exception:
                pass
            return

        base_labels = {
            mode: DISTILL_MODE_LABELS[mode] for mode in PRIMARY_DISTILL_MODES
        }
        by_mode = result.get("by_mode") or {}
        for mode, base in base_labels.items():
            try:
                button = self.query_one(f"#radio-distill-{mode}", RadioButton)
            except Exception:
                continue
            info = by_mode.get(mode) or {}
            detail = str(info.get("detail", ""))
            ready = bool(info.get("ready", False))
            if mode == "cursor":
                suffix = f" — {detail}" if detail else ""
            elif ready:
                suffix = " — ready"
            else:
                suffix = f" — {detail}" if detail else " — unreachable"
            button.label = f"{base}{suffix}"

        try:
            status = self.query_one("#wizard-distill-status", Static)
            status.update(
                f"[dim]{escape_markup(result.get('line', ''))}[/]"
            )
        except Exception:
            pass

    def _handle_wizard_result(self, result: dict[str, Any]) -> None:
        step = result.get("step", "")

        if step == STEP_INSTALL:
            for path in result.get("files_written", []):
                self.log_panel.log_plain(f"  wrote {path}")
            for path in result.get("files_skipped", []):
                self.log_panel.log_plain(f"  kept  {path}")
            for warning in result.get("warnings", []):
                self.log_panel.log_warning(warning)
            status = self.query_one("#wizard-install-status", Static)
            status.update("[bold green]✓ Install complete[/]")
            self._advance()

        elif step == STEP_DOCTOR:
            if result.get("error"):
                self.log_panel.log_error(f"Doctor failed: {result['error']}")
                status = self.query_one("#wizard-doctor-status", Static)
                status.update(f"[bold red]✗ {escape_markup(str(result['error']))}[/]")
            else:
                for line in result.get("formatted", "").strip().splitlines():
                    self.log_panel.log_plain(line)
                status = self.query_one("#wizard-doctor-status", Static)
                recommended = escape_markup(str(result.get("recommended", "?")))
                reachable = result.get("reachable", False)
                state = "[bold green]●[/]" if reachable else "[bold red]●[/]"
                status.update(
                    f"{state} Ollama {'reachable' if reachable else 'unreachable'} "
                    f"| Recommended: [bold]{recommended}[/]"
                )
            self._advance()

        elif step == STEP_DISTILL:
            self.log_panel.log_success(f"Distill mode set to: {result.get('mode', '?')}")
            self._advance()
            # Agent CLI is only an upgrade for cursor — skip the step otherwise.
            if (
                self._distill_mode != "cursor"
                and self._current_step < len(STEPS)
                and STEPS[self._current_step] == STEP_CURSOR_CLI
            ):
                self.log_panel.log_info(
                    "Skipping Agent CLI step — only upgrades cursor mode"
                )
                self._advance()

        elif step == STEP_CURSOR_CLI:
            if result.get("error"):
                self.log_panel.log_warning(f"Cursor agent CLI step: {result['error']}")
                status = self.query_one("#wizard-cursor-cli-status", Static)
                status.update(
                    f"[bold yellow]● {escape_markup(str(result['error']))}[/] "
                    "— heuristic distill still works"
                )
            else:
                if result.get("installed"):
                    self.log_panel.log_info("Ran official Cursor agent install script")
                for line in result.get("formatted", "").strip().splitlines():
                    self.log_panel.log_plain(line)
                status = self.query_one("#wizard-cursor-cli-status", Static)
                if result.get("found"):
                    path = escape_markup(str(result.get("bin_path", "?")))
                    status.update(f"[bold green]✓ Agent CLI ready[/] ({path})")
                else:
                    err = result.get("install_error") or "not found after install"
                    status.update(
                        f"[bold yellow]● Agent CLI unavailable[/] "
                        f"({escape_markup(str(err))}) — heuristic distill still works"
                    )
            self._advance()

        elif step == STEP_APIKEY:
            if result.get("error"):
                self.log_panel.log_error(f"API key verification failed: {result['error']}")
                status = self.query_one("#wizard-apikey-status", Static)
                status.update(f"[bold red]✗ {escape_markup(str(result['error']))}[/]")
            else:
                reachable = result.get("reachable", False)
                status = self.query_one("#wizard-apikey-status", Static)
                if reachable:
                    masked = escape_markup(str(result.get("masked", "?")))
                    status.update(f"[bold green]✓ Groq reachable[/] (key: {masked})")
                    self.log_panel.log_success("Groq API key verified and reachable")
                else:
                    status.update("[bold yellow]● Key saved but Groq unreachable[/]")
                    self.log_panel.log_warning("Groq API key saved but endpoint unreachable")
            self._advance()

        elif step == STEP_GRAPH:
            if result.get("error"):
                self.log_panel.log_warning(f"Graph sync skipped: {result['error']}")
                status = self.query_one("#wizard-graph-status", Static)
                status.update(f"[bold yellow]● Skipped: {escape_markup(str(result['error']))}[/]")
            else:
                node_count = result.get("node_count", 0)
                self.log_panel.log_success(f"Graph synced: {node_count} code nodes")
                status = self.query_one("#wizard-graph-status", Static)
                status.update(f"[bold green]✓ {node_count} code nodes imported[/]")
            self._advance()

    # ------------------------------------------------------------------
    # Screen switching
    # ------------------------------------------------------------------

    def action_switch_dashboard(self) -> None:
        self.app.switch_screen("dashboard")
