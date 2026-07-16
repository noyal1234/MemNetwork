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
    Checkbox,
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
STEP_CLIENT = "step-client"
STEP_INSTALL = "step-install"
STEP_DOCTOR = "step-doctor"
STEP_SEMANTIC = "step-semantic"
STEP_DISTILL = "step-distill"
STEP_CURSOR_CLI = "step-cursor-cli"
STEP_APIKEY = "step-apikey"
STEP_GRAPH = "step-graph"
STEP_VIZ_LLM = "step-viz-llm"
STEP_DONE = "step-done"

STEPS = [
    STEP_PROJECT,
    STEP_CLIENT,
    STEP_INSTALL,
    STEP_DOCTOR,
    STEP_SEMANTIC,
    STEP_DISTILL,
    STEP_CURSOR_CLI,
    STEP_APIKEY,
    STEP_GRAPH,
    STEP_VIZ_LLM,
    STEP_DONE,
]

CLIENT_LABELS: dict[str, str] = {
    "cursor": "cursor — Cursor IDE (MCP + hooks + rules)",
    "claude": "claude — Claude Code (MCP + .claude hooks + CLAUDE.md)",
    "generic": "generic — any MCP client (AGENTS.md + manual capture/handover)",
}

INSTALL_DESCRIPTIONS: dict[str, str] = {
    "cursor": (
        "Creates .brain/, config.json, Cursor MCP config, hooks, and brainkm.mdc rule."
    ),
    "claude": (
        "Creates .brain/, config.json, Cursor-shaped MCP entry, .claude/hooks.json, "
        "and CLAUDE.md routing snippet."
    ),
    "generic": (
        "Creates .brain/, config.json, and an AGENTS.md tool-routing snippet "
        "(no IDE hooks — use brainkm capture / handover manually)."
    ),
}


class WizardScreen(Screen):
    """First-run wizard.

    Walks through: project dir → agent client → install → hardware doctor →
    semantic quality (consent) → distill mode → Cursor agent CLI (optional) →
    API key → graph sync → viz WebLLM prefetch (optional) → done.
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
        self._client = "cursor"
        self._semantic_enable = False
        self._semantic_rerank = False

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

            # --- Step 2: Agent client ---
            with Vertical(classes="wizard-step", id=STEP_CLIENT):
                yield Static("2 ─ Agent Client", classes="step-title")
                yield Static(
                    "Which coding agent will use this project brain?\n"
                    "This chooses hooks / MCP / AGENTS.md scaffolding on install.",
                    classes="step-description",
                )
                with RadioSet(id="wizard-client-radio"):
                    yield RadioButton(
                        CLIENT_LABELS["cursor"],
                        value=True,
                        id="radio-client-cursor",
                    )
                    yield RadioButton(
                        CLIENT_LABELS["claude"],
                        id="radio-client-claude",
                    )
                    yield RadioButton(
                        CLIENT_LABELS["generic"],
                        id="radio-client-generic",
                    )
                yield Static("", id="wizard-client-status")

            # --- Step 3: Install scaffolding ---
            with Vertical(classes="wizard-step", id=STEP_INSTALL):
                yield Static("3 ─ Install Scaffolding", classes="step-title")
                yield Static(
                    INSTALL_DESCRIPTIONS["cursor"],
                    id="wizard-install-description",
                    classes="step-description",
                )
                yield Static("", id="wizard-install-status")

            # --- Step 4: Hardware doctor (Ollama) ---
            with Vertical(classes="wizard-step", id=STEP_DOCTOR):
                yield Static("4 ─ Hardware Doctor (Ollama)", classes="step-title")
                yield Static(
                    "Detect hardware and recommend an Ollama chat/distill model "
                    "(separate from local retrieval embeddings).",
                    classes="step-description",
                )
                yield Static("", id="wizard-doctor-status")

            # --- Step 5: Semantic quality (retrieval embeddings) ---
            with Vertical(classes="wizard-step", id=STEP_SEMANTIC):
                yield Static("5 ─ Semantic Quality (Optional)", classes="step-title")
                yield Static(
                    "Local retrieval embeddings (MiniLM) — not an Ollama/chat model.\n"
                    "Doctor recommends; you consent. Default stays hashing (zero-dep).",
                    classes="step-description",
                )
                yield Static("", id="wizard-semantic-recommend")
                yield Static("", id="wizard-semantic-deps")
                with RadioSet(id="wizard-semantic-radio"):
                    yield RadioButton(
                        "Enable MiniLM quality (~90 MB download)",
                        id="radio-semantic-enable",
                    )
                    yield RadioButton(
                        "Skip — keep hashing embeddings (recommended on small RAM)",
                        value=True,
                        id="radio-semantic-skip",
                    )
                yield Checkbox(
                    "Also enable cross-encoder rerank (slower, more precise)",
                    id="wizard-rerank-check",
                    value=False,
                )
                yield Static("", id="wizard-semantic-status")

            # --- Step 6: Distill mode ---
            with Vertical(classes="wizard-step", id=STEP_DISTILL):
                yield Static("6 ─ Distill Mode", classes="step-title")
                yield Static(
                    "How should brainkm extract neurons from transcripts?\n"
                    "Pick one backend. Cursor Agent CLI (next step) only upgrades "
                    "cursor distill when the agent client is Cursor.",
                    classes="step-description",
                )
                with RadioSet(id="wizard-distill-radio"):
                    for i, mode in enumerate(PRIMARY_DISTILL_MODES):
                        yield RadioButton(
                            DISTILL_MODE_LABELS[mode],
                            value=(i == 0),
                            id=f"radio-distill-{mode}",
                        )
                yield Static("", id="wizard-distill-status")

            # --- Step 7: Optional Cursor Agent CLI upgrade ---
            with Vertical(classes="wizard-step", id=STEP_CURSOR_CLI):
                yield Static(
                    "7 ─ Upgrade Cursor Distill (Agent CLI, Optional)",
                    classes="step-title",
                )
                yield Static(
                    "Not a separate distill mode. Only upgrades cursor mode when "
                    "agent client is Cursor. Heuristic Cursor distill works without this.",
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

            # --- Step 8: API key ---
            with Vertical(classes="wizard-step", id=STEP_APIKEY):
                yield Static("8 ─ API Key (Optional)", classes="step-title")
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

            # --- Step 9: Graph sync ---
            with Vertical(classes="wizard-step", id=STEP_GRAPH):
                yield Static("9 ─ Graph Sync (Optional)", classes="step-title")
                yield Static(
                    "Run Graphify AST extraction and import into brain.db.",
                    classes="step-description",
                )
                yield Static("", id="wizard-graph-status")

            # --- Step 10: Viz WebLLM prefetch ---
            with Vertical(classes="wizard-step", id=STEP_VIZ_LLM):
                yield Static("10 ─ Viz Chat Model (Optional)", classes="step-title")
                yield Static(
                    "Prefetch an on-device WebLLM model for `brainkm viz` Ask-your-brain.\n"
                    "Weights go to ~/.cache/brainkm/webllm/ (once). The browser still needs\n"
                    "Chrome/Edge + WebGPU; first Ask loads into GPU from your local cache.",
                    classes="step-description",
                )
                with RadioSet(id="wizard-viz-llm-radio"):
                    yield RadioButton(
                        "Llama 3.2 1B — recommended (~1 GB)",
                        value=True,
                        id="radio-viz-1b",
                    )
                    yield RadioButton(
                        "Llama 3.2 3B — best quality (~2 GB)",
                        id="radio-viz-3b",
                    )
                    yield RadioButton(
                        "SmolLM2 360M — lightest (~0.3 GB)",
                        id="radio-viz-smol",
                    )
                yield Static("", id="wizard-viz-llm-status")

            # --- Done ---
            with Vertical(classes="wizard-step", id=STEP_DONE):
                yield Static("✓ Setup Complete!", classes="step-title")
                yield Static(
                    "Your project brain is ready. Switch to the Dashboard to see the status.\n"
                    "Open viz with: brainkm viz  ·  Ask chat uses your prefetched model if cached.",
                    id="wizard-done-description",
                    classes="step-description",
                )

            # --- Log panel ---
            yield RichLogPanel(title="[ WIZARD LOG ]", id="wizard-log")

            # --- Navigation buttons ---
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

        if not is_done and STEPS[self._current_step] == STEP_SEMANTIC:
            self._refresh_semantic_step()

    def _refresh_semantic_step(self) -> None:
        """Populate recommendation labels and default radio for Semantic Quality."""
        try:
            from brainkm.services.semantic import semantic_ready
            from brainkm.services.semantic_advisor import (
                format_semantic_recommend,
                recommend_semantic_profile,
            )

            rec = recommend_semantic_profile()
            ready = semantic_ready(self._project_dir)
            recommend_el = self.query_one("#wizard-semantic-recommend", Static)
            recommend_el.update(escape_markup(format_semantic_recommend(rec)))
            deps_el = self.query_one("#wizard-semantic-deps", Static)
            deps_el.update(
                escape_markup(
                    f"Deps: onnx={ready.get('onnxruntime')} tokenizers={ready.get('tokenizers')} "
                    f"hf={ready.get('huggingface_hub')} | "
                    f"cached MiniLM={ready.get('biencoder_cached')} CE={ready.get('cross_encoder_cached')}\n"
                    f"If deps missing: {ready.get('deps_install_hint')}"
                )
            )
            radio = self.query_one("#wizard-semantic-radio", RadioSet)
            # pressed_index: 0=enable, 1=skip — match recommendation.
            if rec.recommend_enable:
                radio.action_first_button()
                # ensure enable selected
                for i, _child in enumerate(radio.children):
                    pass
                # Textual: set via pressing enable button id
                try:
                    enable_btn = self.query_one("#radio-semantic-enable", RadioButton)
                    enable_btn.value = True
                except Exception:
                    pass
            else:
                try:
                    skip_btn = self.query_one("#radio-semantic-skip", RadioButton)
                    skip_btn.value = True
                except Exception:
                    pass
            try:
                check = self.query_one("#wizard-rerank-check", Checkbox)
                check.value = False
                check.disabled = not rec.recommend_enable
            except Exception:
                pass
        except Exception as exc:
            self.log_panel.log_warning(f"Semantic recommend failed: {exc}")

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id != "wizard-semantic-radio":
            return
        try:
            check = self.query_one("#wizard-rerank-check", Checkbox)
            # index 0 = enable MiniLM
            enabling = event.radio_set.pressed_index == 0
            check.disabled = not enabling
            if not enabling:
                check.value = False
        except Exception:
            pass

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
        if step == STEP_SEMANTIC:
            self.log_panel.log_info("Skipped semantic quality — hashing remains default")
            try:
                status = self.query_one("#wizard-semantic-status", Static)
                status.update("[dim]● Skipped — FTS + PPR only (T0)[/]")
            except Exception:
                pass
        elif step == STEP_CURSOR_CLI:
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
        elif step == STEP_VIZ_LLM:
            self.log_panel.log_info(
                "Skipped WebLLM prefetch — load a model later in the viz Ask panel"
            )
            try:
                status = self.query_one("#wizard-viz-llm-status", Static)
                status.update("[dim]● Skipped — download on first Ask instead[/]")
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
            STEP_CLIENT: self._apply_client,
            STEP_INSTALL: self._run_install,
            STEP_DOCTOR: self._run_doctor,
            STEP_SEMANTIC: self._apply_semantic,
            STEP_DISTILL: self._apply_distill_mode,
            STEP_CURSOR_CLI: self._run_cursor_cli,
            STEP_APIKEY: self._apply_api_key,
            STEP_GRAPH: self._run_graph_sync,
            STEP_VIZ_LLM: self._run_viz_llm_prefetch,
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

    def _apply_client(self) -> None:
        """Step 2: Persist agent-client choice for install."""
        mode_map = {0: "cursor", 1: "claude", 2: "generic"}
        try:
            radio_set = self.query_one("#wizard-client-radio", RadioSet)
            self._client = mode_map.get(radio_set.pressed_index, "cursor")
        except Exception:
            self._client = "cursor"

        try:
            status = self.query_one("#wizard-client-status", Static)
            status.update(
                f"[bold green]● Client: {self._client}[/]"
            )
            desc = self.query_one("#wizard-install-description", Static)
            desc.update(INSTALL_DESCRIPTIONS.get(self._client, INSTALL_DESCRIPTIONS["cursor"]))
        except Exception:
            pass
        self.log_panel.log_info(f"Selected agent client: {self._client}")
        self._advance()

    def _run_install(self) -> None:
        self.log_panel.log_info(
            f"Running brainkm install --dev --client {self._client}…"
        )
        self._do_install()

    @work(thread=True, group="wizard", exit_on_error=False)
    def _do_install(self) -> dict[str, Any]:
        from brainkm.services.install import run_install

        try:
            result = run_install(
                project_dir=self._project_dir,
                dev=True,
                force=False,
                no_graph=True,
                client=self._client,
            )
        except Exception as exc:
            return {"step": STEP_INSTALL, "error": str(exc), "client": self._client}
        return {
            "step": STEP_INSTALL,
            "client": self._client,
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

    def _apply_semantic(self) -> None:
        """Step 5: consent for MiniLM (+ optional CE). Skip leaves defaults."""
        try:
            radio = self.query_one("#wizard-semantic-radio", RadioSet)
            self._semantic_enable = radio.pressed_index == 0
        except Exception:
            self._semantic_enable = False
        try:
            check = self.query_one("#wizard-rerank-check", Checkbox)
            self._semantic_rerank = bool(check.value) and self._semantic_enable
        except Exception:
            self._semantic_rerank = False

        if not self._semantic_enable:
            self.log_panel.log_info("Semantic quality skipped — hashing embeddings remain default")
            try:
                status = self.query_one("#wizard-semantic-status", Static)
                status.update("[dim]● Skipped — FTS + PPR only (T0)[/]")
            except Exception:
                pass
            self._advance()
            return

        self.log_panel.log_info(
            f"Enabling MiniLM (rerank={self._semantic_rerank}) — may download ~90 MB…"
        )
        self._do_semantic_enable()

    @work(thread=True, group="wizard", exit_on_error=False)
    def _do_semantic_enable(self) -> dict[str, Any]:
        import json

        from brainkm.adapters.onnx_models import ensure_semantic_models
        from brainkm.services.config_loader import config_path, load_brain_config
        from brainkm.services.semantic import semantic_ready

        ready = semantic_ready(self._project_dir)
        missing_deps = not (
            ready.get("onnxruntime")
            and ready.get("tokenizers")
            and ready.get("huggingface_hub")
        )
        if missing_deps:
            return {
                "step": STEP_SEMANTIC,
                "error": (
                    f"Missing [semantic] deps. Install with: {ready.get('deps_install_hint')} "
                    "then re-run this step or enable in Config editor."
                ),
                "deps_hint": ready.get("deps_install_hint"),
            }

        flags = ensure_semantic_models(include_cross_encoder=self._semantic_rerank)
        if not flags.get("biencoder"):
            return {
                "step": STEP_SEMANTIC,
                "error": "MiniLM download/cache failed — left hashing; try again later.",
            }
        if self._semantic_rerank and not flags.get("cross_encoder"):
            # Still enable semantic; warn about CE
            ce_warn = "Cross-encoder cache failed — rerank will use cosine fallback."
        else:
            ce_warn = None

        cfg = load_brain_config(self._project_dir)
        data = cfg.model_dump(mode="json")
        data.setdefault("semantic", {})
        data["semantic"]["enabled"] = True
        data.setdefault("recall", {})
        data["recall"]["rerank"] = bool(self._semantic_rerank)
        path = config_path(self._project_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return {
            "step": STEP_SEMANTIC,
            "enabled": True,
            "rerank": self._semantic_rerank,
            "warning": ce_warn,
        }

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
        """Read distill radio selection and write to config."""
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
        """Optional Agent CLI upgrade — only for Cursor client + cursor distill."""
        cursor_relevant = self._client == "cursor" and self._distill_mode == "cursor"
        try:
            desc = self.query_one("#wizard-cursor-cli-description", Static)
            if cursor_relevant:
                desc.update(
                    "Not a separate distill mode. Only upgrades cursor mode: "
                    "heuristic Cursor distill already works without this. "
                    "Install the agent CLI for optional LLM-quality extraction."
                )
            else:
                desc.update(
                    "Skipped — Agent CLI only applies when agent client is Cursor "
                    f"and distill_mode is cursor "
                    f"(client={self._client}, distill={self._distill_mode})."
                )
        except Exception:
            pass
        if not cursor_relevant:
            self.log_panel.log_info(
                "Skipping Agent CLI — requires client=cursor and distill_mode=cursor"
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

    def _selected_viz_model_id(self) -> str:
        from brainkm.services.webllm_prefetch import DEFAULT_MODEL_ID

        mapping = {
            0: "Llama-3.2-1B-Instruct-q4f16_1-MLC",
            1: "Llama-3.2-3B-Instruct-q4f16_1-MLC",
            2: "SmolLM2-360M-Instruct-q4f16_1-MLC",
        }
        try:
            radio = self.query_one("#wizard-viz-llm-radio", RadioSet)
            return mapping.get(radio.pressed_index, DEFAULT_MODEL_ID)
        except Exception:
            return DEFAULT_MODEL_ID

    def _run_viz_llm_prefetch(self) -> None:
        model_id = self._selected_viz_model_id()
        self.log_panel.log_info(f"Prefetching WebLLM model: {model_id}")
        self.log_panel.log_plain("  (large download — progress appears below)")
        self._do_viz_llm_prefetch(model_id)

    @work(thread=True, group="wizard", exit_on_error=False)
    def _do_viz_llm_prefetch(self, model_id: str) -> dict[str, Any]:
        import json

        from brainkm.services.config_loader import config_path
        from brainkm.services.webllm_prefetch import prefetch_webllm_model

        progress_lines: list[str] = []

        def progress(name: str, done: int, total: int) -> None:
            if name == "done":
                progress_lines.append(f"  finished {total} files")
            elif done == 0 or done % 5 == 0 or done + 1 == total:
                progress_lines.append(f"  [{done}/{total}] {name}")

        result = prefetch_webllm_model(model_id, progress=progress)

        # Persist preference into .brain/config.json
        cp = config_path(self._project_dir)
        if cp.is_file():
            cfg = json.loads(cp.read_text(encoding="utf-8"))
        else:
            cfg = {}
        cfg.setdefault("viz", {})["webllm_model"] = model_id
        cfg["viz"]["webllm_prefetch"] = True
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")

        out: dict[str, Any] = {
            "step": STEP_VIZ_LLM,
            "model_id": model_id,
            "cache_dir": str(result.cache_dir),
            "files_downloaded": result.files_downloaded,
            "files_skipped": result.files_skipped,
            "bytes_downloaded": result.bytes_downloaded,
            "already_cached": result.already_cached,
            "progress": progress_lines,
        }
        if result.error:
            out["error"] = result.error
        return out

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
            if result.get("error"):
                self.log_panel.log_error(f"Install failed: {result['error']}")
                status = self.query_one("#wizard-install-status", Static)
                status.update(f"[bold red]✗ {escape_markup(str(result['error']))}[/]")
                return
            for path in result.get("files_written", []):
                self.log_panel.log_plain(f"  wrote {path}")
            for path in result.get("files_skipped", []):
                self.log_panel.log_plain(f"  kept  {path}")
            for warning in result.get("warnings", []):
                self.log_panel.log_warning(warning)
            status = self.query_one("#wizard-install-status", Static)
            client = result.get("client", self._client)
            status.update(f"[bold green]✓ Install complete (client={client})[/]")
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

        elif step == STEP_SEMANTIC:
            status = self.query_one("#wizard-semantic-status", Static)
            if result.get("error"):
                self.log_panel.log_error(str(result["error"]))
                status.update(f"[bold yellow]● {escape_markup(str(result['error']))}[/]")
                # Advance anyway — T0 remains usable.
                self._advance()
                return
            if result.get("warning"):
                self.log_panel.log_warning(str(result["warning"]))
            self.log_panel.log_success(
                f"Semantic enabled (rerank={result.get('rerank', False)})"
            )
            status.update(
                f"[bold green]✓ MiniLM enabled[/] "
                f"(rerank={'on' if result.get('rerank') else 'off'})"
            )
            self._advance()

        elif step == STEP_DISTILL:
            self.log_panel.log_success(f"Distill mode set to: {result.get('mode', '?')}")
            self._advance()
            # Agent CLI is only an upgrade for Cursor client + cursor distill.
            if (
                (self._distill_mode != "cursor" or self._client != "cursor")
                and self._current_step < len(STEPS)
                and STEPS[self._current_step] == STEP_CURSOR_CLI
            ):
                self.log_panel.log_info(
                    "Skipping Agent CLI step — requires client=cursor and distill_mode=cursor"
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

        elif step == STEP_VIZ_LLM:
            for line in result.get("progress") or []:
                self.log_panel.log_plain(line)
            status = self.query_one("#wizard-viz-llm-status", Static)
            model_id = escape_markup(str(result.get("model_id", "?")))
            if result.get("error"):
                self.log_panel.log_warning(f"WebLLM prefetch: {result['error']}")
                status.update(
                    f"[bold yellow]● Prefetch failed[/] ({model_id}) — "
                    "Ask can still download in-browser later"
                )
            elif result.get("already_cached"):
                self.log_panel.log_success(f"Already cached: {result.get('cache_dir')}")
                status.update(f"[bold green]✓ Already cached[/] {model_id}")
            else:
                mb = int(result.get("bytes_downloaded", 0)) / (1024 * 1024)
                self.log_panel.log_success(
                    f"Downloaded {result.get('files_downloaded', 0)} files "
                    f"({mb:.0f} MB) → {result.get('cache_dir')}"
                )
                status.update(
                    f"[bold green]✓ Prefetched[/] {model_id} "
                    f"({result.get('files_downloaded', 0)} files)"
                )
            self._advance()

    # ------------------------------------------------------------------
    # Screen switching
    # ------------------------------------------------------------------

    def action_switch_dashboard(self) -> None:
        self.app.switch_screen("dashboard")
