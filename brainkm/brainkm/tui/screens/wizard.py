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

from brainkm.tui.widgets.rich_log_panel import RichLogPanel

# ---------------------------------------------------------------------------
# Wizard step IDs
# ---------------------------------------------------------------------------
STEP_PROJECT = "step-project"
STEP_INSTALL = "step-install"
STEP_DOCTOR = "step-doctor"
STEP_DISTILL = "step-distill"
STEP_APIKEY = "step-apikey"
STEP_GRAPH = "step-graph"
STEP_DONE = "step-done"

STEPS = [STEP_PROJECT, STEP_INSTALL, STEP_DOCTOR, STEP_DISTILL, STEP_APIKEY, STEP_GRAPH, STEP_DONE]


class WizardScreen(Screen):
    """Phase 4 — guided first-run wizard.

    Walks through: project dir → install → hardware doctor → distill mode
    → API key → graph sync → done.
    """

    BINDINGS = [
        ("d", "switch_dashboard", "Dashboard"),
        ("escape", "switch_dashboard", "Back"),
    ]

    def __init__(self, project_dir: Path | None = None) -> None:
        super().__init__()
        self._project_dir = project_dir or Path.cwd()
        self._current_step = 0
        self._distill_mode = "rules"

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="wizard-container"):
            yield Static(
                "🧙 First-Run Wizard",
                classes="panel-title",
            )
            yield Static(
                "[dim]Set up your project brain step by step[/]",
                classes="value--muted",
            )

            # --- Step 1: Project directory ---
            with Vertical(classes="wizard-step", id=STEP_PROJECT):
                yield Static("1 ─ Project Directory", classes="step-title")
                yield Static(
                    f"Project: [bold]{self._project_dir}[/]",
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
                    "How should brainkm extract neurons from transcripts?",
                    classes="step-description",
                )
                with RadioSet(id="wizard-distill-radio"):
                    yield RadioButton("rules — Zero-dependency default; offline", value=True)
                    yield RadioButton("ollama — Local LLM on your machine")
                    yield RadioButton("groq — Free cloud API (needs API key)")
                    yield RadioButton("cursor — Cursor-side distill (V1 stub)")

            # --- Step 5: API key ---
            with Vertical(classes="wizard-step", id=STEP_APIKEY):
                yield Static("5 ─ API Key (Optional)", classes="step-title")
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

            # --- Step 6: Graph sync ---
            with Vertical(classes="wizard-step", id=STEP_GRAPH):
                yield Static("6 ─ Graph Sync (Optional)", classes="step-title")
                yield Static(
                    "Run Graphify AST extraction and import into brain.db.",
                    classes="step-description",
                )
                yield Static("", id="wizard-graph-status")

            # --- Step 7: Done ---
            with Vertical(classes="wizard-step", id=STEP_DONE):
                yield Static("✓ Setup Complete!", classes="step-title")
                yield Static(
                    "Your project brain is ready. Switch to the Dashboard to see the status.",
                    classes="step-description",
                )

            # --- Log panel ---
            yield RichLogPanel(title="📜 Wizard Log", id="wizard-log")

        # --- Navigation buttons ---
        with Horizontal(id="wizard-nav"):
            yield Button("← Back", id="btn-wizard-back", disabled=True)
            yield Button("Run Step", id="btn-wizard-run", classes="-primary")
            yield Button("Skip →", id="btn-wizard-skip")
            yield Button("→ Dashboard", id="btn-wizard-finish", disabled=True)
        yield Footer()

    @property
    def log_panel(self) -> RichLogPanel:
        return self.query_one("#wizard-log", RichLogPanel)

    def on_mount(self) -> None:
        self._update_step_visibility()
        self._check_project()

    # ------------------------------------------------------------------
    # Step management
    # ------------------------------------------------------------------

    def _update_step_visibility(self) -> None:
        """Highlight the current step, dim completed ones."""
        for i, step_id in enumerate(STEPS):
            try:
                step = self.query_one(f"#{step_id}")
            except Exception:
                continue
            if i < self._current_step:
                step.styles.opacity = 0.5
            elif i == self._current_step:
                step.styles.opacity = 1.0
                step.styles.border = ("round", "violet")
            else:
                step.styles.opacity = 0.4

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
            self._advance()
        elif btn_id == "btn-wizard-finish":
            self.action_switch_dashboard()

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

    def _apply_distill_mode(self) -> None:
        """Step 4: Read radio selection and write to config."""
        mode_map = {0: "rules", 1: "ollama", 2: "groq", 3: "cursor"}
        try:
            radio_set = self.query_one("#wizard-distill-radio", RadioSet)
            idx = radio_set.pressed_index
            self._distill_mode = mode_map.get(idx, "rules")
        except Exception:
            self._distill_mode = "rules"

        self.log_panel.log_info(f"Selected distill mode: {self._distill_mode}")
        self._do_apply_distill()

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
        if event.worker.group != "wizard":
            return
        if event.state == WorkerState.SUCCESS:
            self._handle_wizard_result(event.worker.result)
        elif event.state == WorkerState.ERROR:
            self.log_panel.log_error(f"Step failed: {event.worker.error}")

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
                status.update(f"[bold red]✗ {result['error']}[/]")
            else:
                for line in result.get("formatted", "").strip().splitlines():
                    self.log_panel.log_plain(line)
                status = self.query_one("#wizard-doctor-status", Static)
                recommended = result.get("recommended", "?")
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

        elif step == STEP_APIKEY:
            if result.get("error"):
                self.log_panel.log_error(f"API key verification failed: {result['error']}")
                status = self.query_one("#wizard-apikey-status", Static)
                status.update(f"[bold red]✗ {result['error']}[/]")
            else:
                reachable = result.get("reachable", False)
                status = self.query_one("#wizard-apikey-status", Static)
                if reachable:
                    masked = result.get("masked", "?")
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
                status.update(f"[bold yellow]● Skipped: {result['error']}[/]")
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
