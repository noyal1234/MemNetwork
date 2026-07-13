"""Dashboard screen — read-only status overview of the project brain."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static
from textual.worker import Worker, WorkerState

from brainkm.tui.widgets.review_table import ReviewTable
from brainkm.tui.widgets.status_panel import StatusPanel


class DashboardScreen(Screen):
    """Phase 1 — read-only dashboard showing brain health at a glance."""

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("c", "switch_config", "Config"),
        ("a", "switch_actions", "Actions"),
        ("w", "switch_wizard", "Wizard"),
    ]

    def __init__(self, project_dir: Path | None = None) -> None:
        super().__init__()
        self._project_dir = project_dir
        self._last_ollama_data: dict[str, Any] = {}
        self._last_groq_data: dict[str, Any] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="dashboard-container"):
            # --- Brain summary row ---
            with Horizontal(id="brain-summary"):
                yield StatusPanel(title="🧠 Brain Status", id="brain-status")
                yield StatusPanel(title="⚡ Channels", id="channel-status")

            # --- Doctor row ---
            with Horizontal(id="doctor-row"):
                yield StatusPanel(title="🦙 Ollama Doctor", id="ollama-panel")
                yield StatusPanel(title="☁  Groq Doctor", id="groq-panel")

            # --- Graph section ---
            yield StatusPanel(title="🔗 Code Graph", id="graph-panel")

            # --- Review section ---
            with Vertical(id="review-section"):
                yield Static(
                    "📋 Review Queue",
                    classes="panel-title",
                )
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

    # --- Brain status ---

    @work(thread=True, group="brain-status", exit_on_error=False)
    def _load_brain_status(self) -> dict[str, Any]:
        from brainkm.db.connection import connect
        from brainkm.db.paths import brain_db_path

        result: dict[str, Any] = {}
        try:
            from brainkm.services.config_loader import load_brain_config

            cfg = load_brain_config(self._project_dir)
            result["distill_mode"] = cfg.capture.distill_mode
        except Exception:
            result["distill_mode"] = "unknown"

        try:
            db_path = brain_db_path(self._project_dir)
            result["db_size"] = f"{db_path.stat().st_size / 1024:.0f} KB"
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

    def _render_brain_status(self, data: dict[str, Any]) -> None:
        panel = self.query_one("#brain-status", StatusPanel)
        panel.set_items([
            ("Distill mode", str(data.get("distill_mode", "?")), "muted"),
            ("Neurons", str(data.get("neuron_count", 0)), "ok"),
            ("Code nodes", str(data.get("code_node_count", 0)), "ok"),
            ("brain.db", str(data.get("db_size", "?")), "muted"),
        ])

    # --- Ollama ---

    @work(thread=True, group="ollama-status", exit_on_error=False)
    def _load_ollama_status(self) -> dict[str, Any]:
        try:
            from brainkm.services.ollama_advisor import build_doctor_report

            report = build_doctor_report(project_dir=self._project_dir)
            return {
                "reachable": report.ollama.reachable,
                "ram": f"{report.profile.total_ram_gb} GB",
                "gpu": report.profile.gpu_type or "none",
                "recommended": report.recommendation.model,
                "tier": report.recommendation.tier,
                "config_model": report.config_model or "not set",
                "match": report.config_model == report.recommendation.model,
            }
        except Exception as exc:
            return {"reachable": False, "error": str(exc)}

    def _render_ollama_status(self, data: dict[str, Any]) -> None:
        self._last_ollama_data = data
        self._render_channel_status(self._last_ollama_data, self._last_groq_data)
        panel = self.query_one("#ollama-panel", StatusPanel)
        if data.get("error"):
            panel.set_items([
                ("Status", "error", "error"),
                ("Detail", str(data["error"])[:60], "muted"),
            ])
            return
        reachable = data.get("reachable", False)
        items = [
            ("Status", "reachable" if reachable else "unreachable",
             "ok" if reachable else "error"),
            ("RAM", data.get("ram", "?"), "muted"),
            ("GPU", data.get("gpu", "?"), "muted"),
            ("Tier", data.get("tier", "?"), "muted"),
            ("Recommended", data.get("recommended", "?"), "muted"),
        ]
        config_model = data.get("config_model", "?")
        match = data.get("match", False)
        items.append(("Config model", config_model, "ok" if match else "warning"))
        panel.set_items(items)

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
        self._render_channel_status(self._last_ollama_data, self._last_groq_data)
        panel = self.query_one("#groq-panel", StatusPanel)
        if data.get("error") and not data.get("api_key_present", True):
            panel.set_items([
                ("API Key", "not set", "error"),
                ("Detail", str(data.get("error", ""))[:60], "muted"),
            ])
            return
        reachable = data.get("reachable", False)
        panel.set_items([
            ("API Key", data.get("api_key_masked", "?"),
             "ok" if data.get("api_key_present") else "error"),
            ("Status", "reachable" if reachable else "unreachable",
             "ok" if reachable else "error"),
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
            ("Graphify", "found" if graphify_found else "not found",
             "ok" if graphify_found else "warning"),
            ("Code nodes", str(node_count), "ok" if node_count > 0 else "muted"),
            ("Stale", str(stale), "warning" if stale else "ok"),
            ("Auto-sync", str(data.get("auto_sync_enabled", False)), "muted"),
            ("Last import", str(data.get("last_import_status", "none")), "muted"),
        ])

    # --- Channel status ---

    def _render_channel_status(self, ollama_data: dict, groq_data: dict) -> None:
        """Render the channel summary panel from combined data."""
        panel = self.query_one("#channel-status", StatusPanel)
        items = [
            ("Ollama", "up" if ollama_data.get("reachable") else "down",
             "ok" if ollama_data.get("reachable") else "error"),
            ("Groq", "up" if groq_data.get("reachable") else "down",
             "ok" if groq_data.get("reachable") else "error"),
        ]
        panel.set_items(items)

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
        table = self.query_one("#review-table", ReviewTable)
        if items:
            table.set_items(items)
        else:
            table.set_empty()

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
        """Handle worker completion for all status loads."""
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

    # ------------------------------------------------------------------
    # Screen switching
    # ------------------------------------------------------------------

    def action_switch_config(self) -> None:
        self.app.switch_screen("config")

    def action_switch_actions(self) -> None:
        self.app.switch_screen("actions")

    def action_switch_wizard(self) -> None:
        self.app.switch_screen("wizard")
