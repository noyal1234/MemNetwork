"""Dashboard screen — Cyber-Industrial status overview of the project brain."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static
from textual.worker import Worker, WorkerState

from brainkm.tui.theme import bracket_label, escape_markup
from brainkm.tui.widgets.review_table import ReviewTable
from brainkm.tui.widgets.status_panel import StatusPanel


class DashboardScreen(Screen):
    """Read-only dashboard showing brain health at a glance."""

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("c", "switch_config", "Config"),
        ("a", "switch_actions", "Actions"),
        ("w", "switch_wizard", "Wizard"),
        ("y", "approve_selected", "Approve"),
        ("n", "reject_selected", "Reject"),
    ]

    def __init__(self, project_dir: Path | None = None) -> None:
        super().__init__()
        self._project_dir = project_dir
        self._last_brain_data: dict[str, Any] = {}
        self._last_ollama_data: dict[str, Any] = {}
        self._last_groq_data: dict[str, Any] = {}
        self._last_graph_data: dict[str, Any] = {}
        self._pending_review_count = 0

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="dashboard-container"):
            with Horizontal(id="dashboard-body"):
                with Vertical(id="status-sidebar"):
                    yield StatusPanel(title="[ STATUS ]", id="brain-status")

                with Vertical(id="dashboard-main"):
                    with Horizontal(id="doctor-row"):
                        with Vertical(classes="doctor-col"):
                            yield StatusPanel(
                                title="[ OLLAMA DOCTOR ]",
                                id="ollama-panel",
                                classes="emphasized",
                            )
                            with Horizontal(classes="panel-actions"):
                                yield Button(
                                    bracket_label("Apply"),
                                    id="btn-ollama-apply",
                                    classes="-primary",
                                    disabled=True,
                                )
                        with Vertical(classes="doctor-col"):
                            yield StatusPanel(
                                title="[ GROQ DOCTOR ]",
                                id="groq-panel",
                            )
                            with Horizontal(classes="panel-actions"):
                                yield Button(
                                    bracket_label("Refresh"),
                                    id="btn-groq-refresh",
                                )

                    with Vertical(id="graph-section"):
                        with Horizontal(classes="section-header"):
                            yield Static(
                                escape_markup("[ GRAPH VIEWER ]"),
                                classes="section-title",
                            )
                            with Horizontal(classes="graph-actions"):
                                yield Button(bracket_label("Sync"), id="btn-graph-sync")
                                yield Button(
                                    bracket_label("Extract"), id="btn-graph-extract"
                                )
                                yield Button(
                                    bracket_label("Status"),
                                    id="btn-graph-status",
                                    classes="-success",
                                )
                        yield StatusPanel(title="", id="graph-panel")

                    with Vertical(id="review-section"):
                        with Horizontal(classes="review-header"):
                            yield Static(
                                "REVIEW QUEUE (0)",
                                id="review-title",
                                classes="review-title",
                            )
                            yield Static("", id="review-hint", classes="review-hint")
                        yield ReviewTable(id="review-table")
        yield Footer()

    def on_mount(self) -> None:
        """Kick off all status loads on mount."""
        self.action_refresh()

    # ------------------------------------------------------------------
    # Refresh actions — each runs in a worker thread
    # ------------------------------------------------------------------

    def action_refresh(self) -> None:
        """Refresh all dashboard panels."""
        self._load_brain_status()
        self._load_ollama_status()
        self._load_groq_status()
        self._load_graph_status()
        self._load_review_status()

    # --- Brain status (sidebar: brain + channels merged) ---

    @work(thread=True, group="brain-status", exit_on_error=False)
    def _load_brain_status(self) -> dict[str, Any]:
        from brainkm.db.connection import connect
        from brainkm.db.paths import brain_db_path

        result: dict[str, Any] = {}
        try:
            from brainkm.services.config_loader import load_brain_config
            from brainkm.services.distill_status import (
                active_distill_display,
                build_distill_status,
            )

            cfg = load_brain_config(self._project_dir)
            result["distill_mode"] = cfg.capture.distill_mode
            statuses = build_distill_status(project_dir=self._project_dir)
            _mode, display, color = active_distill_display(statuses)
            result["distill_display"] = display
            result["distill_color"] = color
        except Exception:
            result["distill_mode"] = "unknown"
            result["distill_display"] = "unknown"
            result["distill_color"] = "muted"

        try:
            db_path = brain_db_path(self._project_dir)
            size_kb = db_path.stat().st_size / 1024
            if size_kb >= 1024:
                result["db_size"] = f"{size_kb / 1024:.1f} MB"
            else:
                result["db_size"] = f"{size_kb:.0f} KB"
            conn = connect(db_path)
            row = conn.execute(
                "SELECT COUNT(*) as c FROM nodes WHERE kind='memory' AND valid_until IS NULL"
            ).fetchone()
            result["neuron_count"] = row["c"] if row else 0
            code_row = conn.execute(
                "SELECT COUNT(*) as c FROM nodes WHERE kind='code'"
            ).fetchone()
            result["code_node_count"] = code_row["c"] if code_row else 0
            conn.close()
        except Exception:
            result["db_size"] = "n/a"
            result["neuron_count"] = 0
            result["code_node_count"] = 0

        return result

    def _render_brain_status(self, data: dict[str, Any] | None = None) -> None:
        if data is not None:
            self._last_brain_data = data
        brain = self._last_brain_data
        ollama = self._last_ollama_data
        groq = self._last_groq_data
        graph = self._last_graph_data

        panel = self.query_one("#brain-status", StatusPanel)
        distill_value = str(
            brain.get("distill_display") or brain.get("distill_mode", "?")
        )
        distill_color = str(brain.get("distill_color") or "muted")
        items: list[tuple[str, str, str]] = [
            ("distill_mode", distill_value, distill_color),
            (
                "neurons",
                f"{brain.get('neuron_count', 0)} active",
                "ok" if brain.get("neuron_count", 0) else "muted",
            ),
            (
                "code nodes",
                str(brain.get("code_node_count", 0)),
                "ok" if brain.get("code_node_count", 0) else "muted",
            ),
            (
                "pending review",
                f"{self._pending_review_count} items",
                "warning" if self._pending_review_count else "ok",
            ),
        ]

        if ollama:
            if ollama.get("error") and not ollama.get("reachable"):
                items.append(("Ollama", "unreachable", "error"))
            else:
                items.append(
                    (
                        "Ollama",
                        "connected" if ollama.get("reachable") else "unreachable",
                        "ok" if ollama.get("reachable") else "error",
                    )
                )
        if groq:
            items.append(
                (
                    "Groq",
                    "connected" if groq.get("reachable") else "unreachable",
                    "ok" if groq.get("reachable") else "error",
                )
            )
        if graph and not graph.get("error"):
            stale = graph.get("graph_stale", False)
            items.append(
                (
                    "Graph",
                    "stale" if stale else "fresh",
                    "warning" if stale else "ok",
                )
            )
        elif graph and graph.get("error"):
            items.append(("Graph", "error", "error"))

        items.append(("brain.db", str(brain.get("db_size", "?")), "ok"))
        panel.set_items(items)

    # --- Ollama ---

    @work(thread=True, group="ollama-status", exit_on_error=False)
    def _load_ollama_status(self) -> dict[str, Any]:
        try:
            from brainkm.services.ollama_advisor import build_doctor_report

            report = build_doctor_report(project_dir=self._project_dir)
            return {
                "reachable": report.ollama.reachable,
                "ram": f"{report.profile.total_ram_gb:.0f} GB",
                "gpu": "accelerated" if report.profile.has_gpu_accel else "cpu-only",
                "recommended": report.recommendation.model,
                "tier": report.recommendation.tier,
                "config_model": report.config_model or "not set",
                "match": report.config_model == report.recommendation.model,
            }
        except Exception as exc:
            return {"reachable": False, "error": str(exc)}

    def _render_ollama_status(self, data: dict[str, Any]) -> None:
        self._last_ollama_data = data
        self._render_brain_status()
        panel = self.query_one("#ollama-panel", StatusPanel)
        apply_btn = self.query_one("#btn-ollama-apply", Button)

        if data.get("error"):
            panel.set_items([
                ("Status", "error", "error"),
                ("Detail", str(data["error"])[:60], "muted"),
            ])
            apply_btn.disabled = True
            return

        reachable = data.get("reachable", False)
        match = data.get("match", False)
        items = [
            (
                "Status",
                "reachable" if reachable else "unreachable",
                "ok" if reachable else "error",
            ),
            ("RAM", data.get("ram", "?"), "muted"),
            ("GPU", data.get("gpu", "?"), "muted"),
            ("Tier", data.get("tier", "?"), "muted"),
            ("Recommended", data.get("recommended", "?"), "muted"),
        ]
        config_model = data.get("config_model", "?")
        items.append(("Config", config_model, "ok" if match else "warning"))
        panel.set_items(items)
        apply_btn.disabled = bool(match or not reachable or data.get("error"))

    # --- Groq ---

    @work(thread=True, group="groq-status", exit_on_error=False)
    def _load_groq_status(self) -> dict[str, Any]:
        try:
            from brainkm.services.groq_advisor import build_groq_report

            report = build_groq_report(project_dir=self._project_dir)
            return {
                "api_key_present": report.api_key_present,
                "api_key_masked": report.api_key_masked or "not set",
                "reachable": report.status.reachable,
                "config_model": report.config_model or "not set",
                "error": report.status.error,
            }
        except Exception as exc:
            return {"reachable": False, "error": str(exc)}

    def _render_groq_status(self, data: dict[str, Any]) -> None:
        self._last_groq_data = data
        self._render_brain_status()
        panel = self.query_one("#groq-panel", StatusPanel)
        if data.get("error") and not data.get("api_key_present", True):
            panel.set_items([
                ("Key", "not set", "error"),
                ("Detail", str(data.get("error", ""))[:60], "muted"),
            ])
            return
        reachable = data.get("reachable", False)
        panel.set_items([
            (
                "Key",
                data.get("api_key_masked", "?"),
                "ok" if data.get("api_key_present") else "error",
            ),
            (
                "Status",
                "reachable" if reachable else "unreachable",
                "ok" if reachable else "error",
            ),
            ("Model", data.get("config_model", "?"), "muted"),
        ])

    # --- Graph ---

    @work(thread=True, group="graph-status", exit_on_error=False)
    def _load_graph_status(self) -> dict[str, Any]:
        try:
            from brainkm.services.config_loader import load_brain_config
            from brainkm.services.graphify_sync import build_graph_status

            cfg = load_brain_config(self._project_dir)
            return build_graph_status(self._project_dir, cfg)
        except Exception as exc:
            return {"error": str(exc)}

    def _render_graph_status(self, data: dict[str, Any]) -> None:
        self._last_graph_data = data
        self._render_brain_status()
        panel = self.query_one("#graph-panel", StatusPanel)
        if data.get("error"):
            panel.set_items([
                ("Status", "error", "error"),
                ("Detail", str(data["error"])[:60], "muted"),
            ])
            return
        graphify_found = data.get("graphify_found", False)
        stale = data.get("graph_stale", False)
        node_count = data.get("code_node_count", 0)
        panel.set_items([
            (
                "Engine",
                "graphify" if graphify_found else "not found",
                "ok" if graphify_found else "warning",
            ),
            ("Nodes", str(node_count), "ok" if node_count > 0 else "muted"),
            ("Stale", str(stale).lower(), "warning" if stale else "ok"),
            ("Auto-sync", str(data.get("auto_sync_enabled", False)), "muted"),
            (
                "Watch FS",
                str(data.get("watch_filesystem_enabled", False)),
                "muted",
            ),
            ("Last import", str(data.get("last_import_status", "none")), "muted"),
        ])

    # --- Review ---

    @work(thread=True, group="review-status", exit_on_error=False)
    def _load_review_status(self) -> list[dict]:
        try:
            from brainkm.services.review import list_pending

            items = list_pending(self._project_dir)
            return [
                {
                    "node_id": item.node_id,
                    "subtype": item.subtype or "",
                    "confidence": item.confidence,
                    "title": item.title,
                }
                for item in items
            ]
        except Exception:
            return []

    def _render_review_status(self, items: list[dict]) -> None:
        self._pending_review_count = len(items)
        self._render_brain_status()
        title = self.query_one("#review-title", Static)
        hint = self.query_one("#review-hint", Static)
        title.update(escape_markup(f"REVIEW QUEUE ({len(items)})"))
        hint.update(escape_markup("! ACTION REQUIRED") if items else "")

        table = self.query_one("#review-table", ReviewTable)
        if items:
            table.set_items(items)
        else:
            table.set_empty()

    # ------------------------------------------------------------------
    # Dashboard action buttons
    # ------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        handlers = {
            "btn-ollama-apply": self._run_ollama_apply,
            "btn-groq-refresh": self._run_groq_refresh,
            "btn-graph-sync": self._run_graph_sync,
            "btn-graph-extract": self._run_graph_extract,
            "btn-graph-status": self._run_graph_status_action,
        }
        handler = handlers.get(event.button.id or "")
        if handler:
            handler()

    def _run_groq_refresh(self) -> None:
        self.notify("Refreshing Groq status…", severity="information")
        self._load_groq_status()

    def _run_ollama_apply(self) -> None:
        self.notify("Applying recommended Ollama model…", severity="information")
        self._do_ollama_apply()

    @work(thread=True, group="dashboard-action", exit_on_error=False)
    def _do_ollama_apply(self) -> dict[str, Any]:
        from brainkm.services.ollama_advisor import apply_recommended_model

        try:
            path = apply_recommended_model(project_dir=self._project_dir)
            return {"action": "ollama_apply", "ok": True, "path": str(path)}
        except Exception as exc:
            return {"action": "ollama_apply", "ok": False, "error": str(exc)}

    def _run_graph_sync(self) -> None:
        self.notify("Starting graph sync…", severity="information")
        self._do_graph_sync()

    @work(thread=True, group="dashboard-action", exit_on_error=False)
    def _do_graph_sync(self) -> dict[str, Any]:
        from brainkm.services.config_loader import load_brain_config
        from brainkm.services.graphify_sync import sync_graph

        try:
            cfg = load_brain_config(self._project_dir)
            result = sync_graph(
                project_dir=self._project_dir,
                config=cfg,
                extract=True,
            )
            return {
                "action": "graph_sync",
                "ok": result.status in {"completed", "skipped"},
                "status": result.status,
                "message": result.message,
            }
        except Exception as exc:
            return {"action": "graph_sync", "ok": False, "error": str(exc)}

    def _run_graph_extract(self) -> None:
        self.notify("Running graph extract…", severity="information")
        self._do_graph_extract()

    @work(thread=True, group="dashboard-action", exit_on_error=False)
    def _do_graph_extract(self) -> dict[str, Any]:
        from brainkm.services.config_loader import load_brain_config
        from brainkm.services.graphify_sync import run_graphify_extract

        try:
            root = (
                self._project_dir.resolve()
                if self._project_dir is not None
                else Path.cwd()
            )
            cfg = load_brain_config(self._project_dir)
            result = run_graphify_extract(root, cfg, force=False)
            return {
                "action": "graph_extract",
                "ok": result.ok,
                "message": (
                    str(result.graph_path)
                    if result.ok
                    else (result.stderr_snippet or "extract failed")
                ),
            }
        except Exception as exc:
            return {"action": "graph_extract", "ok": False, "error": str(exc)}

    def _run_graph_status_action(self) -> None:
        self.notify("Refreshing graph status…", severity="information")
        self._load_graph_status()

    # ------------------------------------------------------------------
    # Review approve / reject (y / n on review table)
    # ------------------------------------------------------------------

    def on_review_table_approved(self, event: ReviewTable.Approved) -> None:
        self._approve_review_item(event.node_id)

    def on_review_table_rejected(self, event: ReviewTable.Rejected) -> None:
        self._reject_review_item(event.node_id)

    def _approve_review_item(self, node_id: str) -> None:
        self.notify(f"Approving {node_id[:8]}…", severity="information")
        self._do_approve(node_id)

    def _reject_review_item(self, node_id: str) -> None:
        self.notify(f"Rejecting {node_id[:8]}…", severity="warning")
        self._do_reject(node_id)

    @work(thread=True, group="review-action", exit_on_error=False)
    def _do_approve(self, node_id: str) -> dict:
        from brainkm.db.connection import connect
        from brainkm.db.paths import brain_db_path
        from brainkm.services.review import approve_pending

        conn = connect(brain_db_path(self._project_dir))
        try:
            ok = approve_pending(node_id, conn=conn, project_dir=self._project_dir)
            return {"ok": ok, "node_id": node_id}
        finally:
            conn.close()

    @work(thread=True, group="review-action", exit_on_error=False)
    def _do_reject(self, node_id: str) -> dict:
        from brainkm.db.connection import connect
        from brainkm.db.paths import brain_db_path
        from brainkm.services.review import reject_pending

        conn = connect(brain_db_path(self._project_dir))
        try:
            ok = reject_pending(node_id, conn=conn, project_dir=self._project_dir)
            return {"ok": ok, "node_id": node_id}
        finally:
            conn.close()

    def _on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle worker completion for all status loads and actions."""
        if event.state != WorkerState.SUCCESS:
            return
        worker = event.worker
        if worker.group == "brain-status":
            self._render_brain_status(worker.result)
        elif worker.group == "ollama-status":
            self._render_ollama_status(worker.result)
        elif worker.group == "groq-status":
            self._render_groq_status(worker.result)
        elif worker.group == "graph-status":
            self._render_graph_status(worker.result)
        elif worker.group == "review-status":
            self._render_review_status(worker.result)
        elif worker.group == "review-action":
            result = worker.result
            if result.get("ok"):
                self.notify(f"Done: {result['node_id'][:8]}…", severity="information")
            else:
                self.notify("Review action failed", severity="error")
            self._load_review_status()
        elif worker.group == "dashboard-action":
            self._handle_dashboard_action(worker.result)

    def _handle_dashboard_action(self, result: dict[str, Any]) -> None:
        action = result.get("action", "")
        if not result.get("ok"):
            detail = result.get("error") or result.get("message") or "failed"
            self.notify(escape_markup(f"{action}: {detail}"), severity="error")
            return

        if action == "ollama_apply":
            self.notify("Ollama model applied", severity="information")
            self._load_ollama_status()
            self._load_brain_status()
        elif action == "graph_sync":
            self.notify(
                escape_markup(
                    result.get("message") or f"Graph sync: {result.get('status')}"
                ),
                severity="information",
            )
            self._load_graph_status()
            self._load_brain_status()
        elif action == "graph_extract":
            self.notify(
                escape_markup(f"Extracted: {result.get('message', 'ok')}"),
                severity="information",
            )
            self._load_graph_status()

    # ------------------------------------------------------------------
    # Screen switching
    # ------------------------------------------------------------------

    def action_switch_config(self) -> None:
        self.app.switch_screen("config")

    def action_switch_actions(self) -> None:
        self.app.switch_screen("actions")

    def action_switch_wizard(self) -> None:
        self.app.switch_screen("wizard")

    def action_approve_selected(self) -> None:
        table = self.query_one("#review-table", ReviewTable)
        node_id = table.get_selected_node_id()
        if node_id:
            self._approve_review_item(node_id)

    def action_reject_selected(self) -> None:
        table = self.query_one("#review-table", ReviewTable)
        node_id = table.get_selected_node_id()
        if node_id:
            self._reject_review_item(node_id)
