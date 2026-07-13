"""Actions screen — service invocations with streaming RichLog output."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static
from textual.worker import Worker, WorkerState

from brainkm.tui.widgets.rich_log_panel import RichLogPanel


class ActionsScreen(Screen):
    """Phase 3 — run service operations with live streamed output."""

    BINDINGS = [
        ("d", "switch_dashboard", "Dashboard"),
        ("c", "switch_config", "Config"),
        ("w", "switch_wizard", "Wizard"),
        ("escape", "switch_dashboard", "Back"),
    ]

    def __init__(self, project_dir: Path | None = None) -> None:
        super().__init__()
        self._project_dir = project_dir

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="actions-container"):
            yield Static(
                "⚡ Actions — run service operations",
                classes="panel-title",
            )

            # --- Action buttons (two rows of four — avoids grid gutter artifacts) ---
            with Horizontal(classes="action-buttons-row"):
                yield Button("Graph Sync", id="btn-graph-sync", variant="primary")
                yield Button("Graph Status", id="btn-graph-status")
                yield Button("Ollama Doctor", id="btn-ollama-doctor")
                yield Button("Groq Doctor", id="btn-groq-doctor")

            with Horizontal(classes="action-buttons-row"):
                yield Button("Export", id="btn-export")
                yield Button("Repair", id="btn-repair")
                yield Button("Bench: token", id="btn-bench-token")
                yield Button("Bench: abstention", id="btn-bench-abstention")

            with Horizontal(classes="action-buttons-row"):
                yield Button("Bench: dmr", id="btn-bench-dmr")
                yield Button("Bench: longmem", id="btn-bench-longmem")
                yield Button("Bench: budget", id="btn-bench-budget")
                yield Button("Bench: compaction", id="btn-bench-compaction")

            # --- Log output (primary focus — fills remaining screen height) ---
            yield RichLogPanel(title="📜 Action Log", id="action-log")
        yield Footer()

    @property
    def log_panel(self) -> RichLogPanel:
        return self.query_one("#action-log", RichLogPanel)

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        handlers = {
            "btn-graph-sync": self._run_graph_sync,
            "btn-graph-status": self._run_graph_status,
            "btn-ollama-doctor": self._run_ollama_doctor,
            "btn-groq-doctor": self._run_groq_doctor,
            "btn-export": self._run_export,
            "btn-repair": self._run_repair,
        }
        if btn_id.startswith("btn-bench-"):
            suite = btn_id.replace("btn-bench-", "")
            self._run_bench(suite)
            return

        handler = handlers.get(btn_id)
        if handler:
            handler()
        else:
            self.log_panel.log_warning(f"No handler for button: {btn_id}")

    def _begin_action(self, message: str) -> None:
        """Clear prior output and write a fresh start line."""
        self.log_panel.clear()
        self.log_panel.log_info(message)

    # ------------------------------------------------------------------
    # Service workers
    # ------------------------------------------------------------------

    def _run_graph_sync(self) -> None:
        self._begin_action("Starting graph sync…")
        self._do_graph_sync()

    @work(thread=True, group="action", exit_on_error=False)
    def _do_graph_sync(self) -> dict[str, Any]:
        from brainkm.services.config_loader import load_brain_config
        from brainkm.services.graphify_sync import sync_graph

        cfg = load_brain_config(self._project_dir)
        result = sync_graph(
            project_dir=self._project_dir,
            config=cfg,
            extract=True,
        )
        return {
            "action": "graph_sync",
            "status": result.status,
            "message": result.message,
            "node_count": result.import_result.node_count if result.import_result else 0,
            "edge_count": result.import_result.edge_count if result.import_result else 0,
        }

    def _run_graph_status(self) -> None:
        self._begin_action("Fetching graph status…")
        self._do_graph_status()

    @work(thread=True, group="action", exit_on_error=False)
    def _do_graph_status(self) -> dict[str, Any]:
        from brainkm.services.config_loader import load_brain_config
        from brainkm.services.graphify_sync import build_graph_status

        cfg = load_brain_config(self._project_dir)
        status = build_graph_status(self._project_dir, cfg)
        return {"action": "graph_status", **status}

    def _run_ollama_doctor(self) -> None:
        self._begin_action("Running Ollama doctor…")
        self._do_ollama_doctor()

    @work(thread=True, group="action", exit_on_error=False)
    def _do_ollama_doctor(self) -> dict[str, Any]:
        from brainkm.services.ollama_advisor import build_doctor_report, format_doctor_report

        report = build_doctor_report(project_dir=self._project_dir)
        return {
            "action": "ollama_doctor",
            "formatted": format_doctor_report(report),
        }

    def _run_groq_doctor(self) -> None:
        self._begin_action("Running Groq doctor…")
        self._do_groq_doctor()

    @work(thread=True, group="action", exit_on_error=False)
    def _do_groq_doctor(self) -> dict[str, Any]:
        from brainkm.services.groq_advisor import build_groq_report, format_groq_report

        report = build_groq_report(project_dir=self._project_dir)
        return {
            "action": "groq_doctor",
            "formatted": format_groq_report(report),
        }

    def _run_export(self) -> None:
        self._begin_action("Exporting neurons…")
        self._do_export()

    @work(thread=True, group="action", exit_on_error=False)
    def _do_export(self) -> dict[str, Any]:
        from brainkm.services.export import export_markdown

        result = export_markdown(project_dir=self._project_dir)
        return {
            "action": "export",
            "neuron_count": result.neuron_count,
            "path": str(result.path),
        }

    def _run_repair(self) -> None:
        self._begin_action("Running brain repair…")
        self._do_repair()

    @work(thread=True, group="action", exit_on_error=False)
    def _do_repair(self) -> dict[str, Any]:
        from brainkm.services.repair import repair_brain

        result = repair_brain(project_dir=self._project_dir)
        return {
            "action": "repair",
            "fts_rows": result.fts_rows_rebuilt,
            "integrity_ok": result.integrity_ok,
        }

    def _run_bench(self, suite: str) -> None:
        self._begin_action(f"Running bench suite: {suite}…")
        self._do_bench(suite)

    @work(thread=True, group="action", exit_on_error=False)
    def _do_bench(self, suite: str) -> dict[str, Any]:
        from brainkm.db.paths import brain_db_path
        from brainkm.services.bench_runner import format_suite_result, run_bench_suite

        db_path = brain_db_path(self._project_dir)
        try:
            result = run_bench_suite(suite, db_path)
        except Exception as exc:
            return {"action": "bench", "suite": suite, "error": str(exc)}
        return {
            "action": "bench",
            "suite": suite,
            "formatted": format_suite_result(result),
            "passed": result.passed,
            "total": result.total,
        }

    # ------------------------------------------------------------------
    # Worker result handler
    # ------------------------------------------------------------------

    def _on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.group != "action":
            return

        if event.state == WorkerState.SUCCESS:
            self._handle_action_result(event.worker.result)
        elif event.state == WorkerState.ERROR:
            err = event.worker.error
            self.log_panel.log_error(f"Action failed: {err}")
            self.notify(str(err), severity="error", timeout=8)

    def _handle_action_result(self, result: dict[str, Any]) -> None:
        if not isinstance(result, dict):
            self.log_panel.log_error(f"Unexpected result: {result!r}")
            return

        action = result.get("action", "")

        if action == "graph_sync":
            status = result.get("status", "?")
            if status in ("skipped", "skipped_locked", "skipped_empty"):
                self.log_panel.log_warning(f"Graph sync skipped: {result.get('message', status)}")
            elif status in ("extract_failed", "missing_graph"):
                self.log_panel.log_error(result.get("message", status))
            else:
                self.log_panel.log_success(
                    f"Synced: {result.get('node_count', 0)} code nodes, "
                    f"{result.get('edge_count', 0)} edges (status={status})"
                )

        elif action == "graph_status":
            for key in ("graphify_found", "graph_json_exists", "graph_stale",
                        "graph_available", "code_node_count", "auto_sync_enabled"):
                if key in result:
                    self.log_panel.log_plain(f"{key}: {result[key]}")

        elif action in ("ollama_doctor", "groq_doctor"):
            formatted = result.get("formatted", "")
            for line in formatted.strip().splitlines():
                self.log_panel.log_plain(line)

        elif action == "export":
            self.log_panel.log_success(
                f"Exported {result.get('neuron_count', 0)} neurons to {result.get('path', '?')}"
            )

        elif action == "repair":
            integrity = result.get("integrity_ok", False)
            fts = result.get("fts_rows", 0)
            if integrity:
                self.log_panel.log_success(f"Repair complete: {fts} FTS rows rebuilt, integrity OK")
            else:
                self.log_panel.log_error(f"Repair: {fts} FTS rows rebuilt, integrity FAILED")

        elif action == "bench":
            if result.get("error"):
                self.log_panel.log_error(f"Bench failed: {result['error']}")
                return
            passed = result.get("passed", 0)
            total = result.get("total", 0)
            suite = result.get("suite", "?")
            formatted = result.get("formatted", "")
            for line in formatted.strip().splitlines():
                self.log_panel.log_plain(line)
            if passed == total:
                self.log_panel.log_success(f"{suite}: {passed}/{total} passed")
            else:
                self.log_panel.log_error(f"{suite}: {passed}/{total} passed")

    # ------------------------------------------------------------------
    # Screen switching
    # ------------------------------------------------------------------

    def action_switch_dashboard(self) -> None:
        self.app.switch_screen("dashboard")

    def action_switch_config(self) -> None:
        self.app.switch_screen("config")

    def action_switch_wizard(self) -> None:
        self.app.switch_screen("wizard")
