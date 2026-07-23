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
        ("enter", "review_detail", "Detail"),
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
            yield Static(
                "",
                id="rate-limit-banner",
            )
            with Horizontal(id="dashboard-body"):
                with Vertical(id="status-sidebar"):
                    yield StatusPanel(title="[ STATUS ]", id="brain-status")
                    yield StatusPanel(title="[ SHARED BRAIN ]", id="serve-status")
                    with Horizontal(classes="panel-actions"):
                        yield Button(
                            bracket_label("Start Brain"),
                            id="btn-start-serve",
                            classes="-primary",
                        )
                        yield Button(
                            bracket_label("Stop"),
                            id="btn-stop-serve",
                        )

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

                    with Vertical(id="mcp-doctor-section"):
                        with Horizontal(classes="section-header"):
                            yield Static(
                                escape_markup("[ MCP DOCTOR ]"),
                                classes="section-title",
                            )
                            with Horizontal(classes="graph-actions"):
                                yield Button(
                                    bracket_label("Refresh"),
                                    id="btn-mcp-doctor-refresh",
                                )
                        yield StatusPanel(title="", id="mcp-doctor-panel")

                    with Vertical(id="review-section", classes="review-section--empty"):
                        with Horizontal(classes="review-header"):
                            yield Static(
                                "REVIEW QUEUE (0)",
                                id="review-title",
                                classes="review-title",
                            )
                            yield Static(
                                "Low-confidence auto-captures wait here — Enter detail · y approve / n reject",
                                id="review-hint",
                                classes="review-hint",
                            )
                        yield ReviewTable(id="review-table")
        yield Footer()

    def on_mount(self) -> None:
        """Kick off all status loads on mount."""
        self.action_refresh()

    # ------------------------------------------------------------------
    # Refresh actions — each runs in a worker thread
    # ------------------------------------------------------------------

    def _set_panels_loading(self) -> None:
        """Dim empty panels with a Loading row (skip panels that already have data)."""
        for panel_id, has_data in (
            ("#brain-status", bool(self._last_brain_data)),
            ("#serve-status", False),
            ("#ollama-panel", bool(self._last_ollama_data)),
            ("#groq-panel", bool(self._last_groq_data)),
            ("#graph-panel", bool(self._last_graph_data)),
            ("#mcp-doctor-panel", False),
        ):
            if has_data:
                continue
            try:
                self.query_one(panel_id, StatusPanel).set_loading()
            except Exception:
                pass

    def action_refresh(self) -> None:
        """Refresh all dashboard panels."""
        self._set_panels_loading()
        self._load_brain_status()
        self._load_serve_status()
        self._load_ollama_status()
        self._load_groq_status()
        self._load_graph_status()
        self._load_mcp_doctor()
        self._load_review_status()

    # --- Brain status (sidebar: brain + channels merged) ---

    @work(thread=True, group="brain-status", exit_on_error=False)
    def _load_brain_status(self) -> dict[str, Any]:
        from brainkm.services.brain_status import build_brain_status_summary

        return build_brain_status_summary(self._project_dir)

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
            ("distill", distill_value, distill_color),
            (
                "neurons",
                f"{brain.get('neuron_count', 0)} active",
                "ok" if brain.get("neuron_count", 0) else "muted",
            ),
            (
                "code",
                str(brain.get("code_node_count", 0)),
                "ok" if brain.get("code_node_count", 0) else "muted",
            ),
            (
                "edges",
                str(brain.get("edge_count", 0)),
                "ok" if brain.get("edge_count", 0) else "muted",
            ),
            (
                "observe",
                "on" if brain.get("auto_observe") else "off",
                "ok" if brain.get("auto_observe") else "warning",
            ),
            (
                "mcp",
                str(brain.get("mcp_transport") or "?"),
                "ok" if brain.get("mcp_transport") in {"http", "stdio"} else "muted",
            ),
            (
                "Commit Trace",
                str(brain.get("commit_trace_label") or "?"),
                str(brain.get("commit_trace_color") or "muted"),
            ),
            (
                "review",
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
            rate_limited = bool(groq.get("rate_limited")) or (
                "429" in str(groq.get("error") or "")
            )
            if rate_limited:
                items.append(("Groq", "RATE LIMITED", "error"))
            else:
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

    @work(thread=True, group="serve-status", exit_on_error=False)
    def _load_serve_status(self) -> dict[str, Any]:
        try:
            from brainkm.services.config_loader import load_brain_config
            from brainkm.services.mcp_doctor import (
                antigravity_hooks_wired,
                claude_hooks_wired,
                codex_hooks_wired,
            )
            from brainkm.services.serve_helper import get_serve_status

            cfg = load_brain_config(self._project_dir)
            status = get_serve_status(self._project_dir)
            claude_dir = (self._project_dir / ".claude").is_dir() or (
                self._project_dir / ".mcp.json"
            ).is_file()
            agy_dir = (self._project_dir / ".agents").is_dir()
            codex_dir = (self._project_dir / ".codex").is_dir()
            return {
                "running": status.running,
                "transport": cfg.mcp.transport,
                "auto_observe": cfg.capture.auto_observe,
                "url": status.health_url,
                "detail": status.detail,
                "claude_hooks": claude_hooks_wired(self._project_dir) if claude_dir else None,
                "antigravity_hooks": (
                    antigravity_hooks_wired(self._project_dir) if agy_dir else None
                ),
                "codex_hooks": (
                    codex_hooks_wired(self._project_dir) if codex_dir else None
                ),
            }
        except Exception as exc:
            return {"error": str(exc), "running": False, "transport": "?"}

    def _render_serve_status(self, data: dict[str, Any]) -> None:
        panel = self.query_one("#serve-status", StatusPanel)
        start_btn = self.query_one("#btn-start-serve", Button)
        stop_btn = self.query_one("#btn-stop-serve", Button)
        if data.get("error"):
            panel.set_items([("Status", "error", "error"), ("Detail", str(data["error"])[:40], "muted")])
            return
        transport = str(data.get("transport", "?"))
        running = bool(data.get("running"))
        items: list[tuple[str, str, str]]
        if transport == "stdio":
            items = [
                ("Mode", "simple (auto)", "ok"),
                ("Observe", "on" if data.get("auto_observe") else "off", "ok"),
                ("Note", "no serve needed", "muted"),
            ]
            start_btn.disabled = True
            stop_btn.disabled = True
        else:
            items = [
                ("Mode", "shared HTTP", "accent"),
                ("Server", "running" if running else "stopped", "ok" if running else "warning"),
                ("Observe", "on" if data.get("auto_observe") else "off", "ok"),
                ("URL", str(data.get("url", ""))[:48], "muted"),
            ]
            start_btn.disabled = running
            stop_btn.disabled = not running
        claude_hooks = data.get("claude_hooks")
        if claude_hooks is True:
            items.append(("Claude hooks", "settings.json", "ok"))
        elif claude_hooks is False:
            items.append(("Claude hooks", "missing", "warning"))
        agy_hooks = data.get("antigravity_hooks")
        if agy_hooks is True:
            items.append(("AGY hooks", ".agents/hooks.json", "ok"))
        elif agy_hooks is False:
            items.append(("AGY hooks", "missing", "warning"))
        codex_hooks = data.get("codex_hooks")
        if codex_hooks is True:
            items.append(("Codex hooks", ".codex/hooks.json", "ok"))
        elif codex_hooks is False:
            items.append(("Codex hooks", "missing", "warning"))
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
        recommended = str(data.get("recommended") or "?")
        config_model = str(data.get("config_model") or "?")
        items = [
            (
                "Status",
                "reachable" if reachable else "unreachable",
                "ok" if reachable else "error",
            ),
            ("RAM", data.get("ram", "?"), "info"),
            ("GPU", data.get("gpu", "?"), "info"),
            ("Tier", data.get("tier", "?"), "info"),
            ("Model", recommended, "accent"),
            ("Config", config_model, "accent"),
            (
                "Match",
                "yes" if match else "no",
                "ok" if match else "warning",
            ),
        ]
        panel.set_items(items)
        apply_btn.disabled = bool(match or not reachable or data.get("error"))

    # --- Groq ---

    @work(thread=True, group="groq-status", exit_on_error=False)
    def _load_groq_status(self) -> dict[str, Any]:
        try:
            from brainkm.services.groq_advisor import build_groq_report

            report = build_groq_report(project_dir=self._project_dir)
            model = report.config_model or (
                report.status.models[0] if report.status.models else None
            )
            return {
                "api_key_present": report.api_key_present,
                "api_key_masked": report.api_key_masked or "not set",
                "reachable": report.status.reachable,
                "config_model": model or "not set",
                "error": report.status.error,
                "rate_limited": report.status.rate_limited,
            }
        except Exception as exc:
            return {"reachable": False, "error": str(exc), "rate_limited": False}

    def _render_groq_status(self, data: dict[str, Any]) -> None:
        self._last_groq_data = data
        self._render_brain_status()
        self._update_rate_limit_banner(data)
        panel = self.query_one("#groq-panel", StatusPanel)
        if data.get("error") and not data.get("api_key_present", True):
            panel.set_items([
                ("Key", "not set", "error"),
                ("Detail", str(data.get("error", ""))[:60], "muted"),
            ])
            return

        reachable = data.get("reachable", False)
        rate_limited = bool(data.get("rate_limited"))
        model = str(data.get("config_model") or "not set").strip() or "not set"
        items: list[tuple[str, str, str]] = [
            (
                "Key",
                data.get("api_key_masked", "?"),
                "ok" if data.get("api_key_present") else "error",
            ),
        ]
        if rate_limited:
            items.append(("Status", "RATE LIMITED", "error"))
            detail = str(data.get("error") or "HTTP 429")[:72]
            items.append(("Detail", detail, "error"))
        else:
            items.append(
                (
                    "Status",
                    "reachable" if reachable else "unreachable",
                    "ok" if reachable else "error",
                )
            )
            if data.get("error") and not reachable:
                items.append(("Detail", str(data["error"])[:72], "muted"))
        items.append(("Model", model, "accent"))
        panel.set_items(items)
        if rate_limited:
            self.notify(
                escape_markup("Groq rate limit hit (HTTP 429) — distill may fall back"),
                severity="error",
                timeout=6,
            )

    def _update_rate_limit_banner(self, data: dict[str, Any]) -> None:
        try:
            banner = self.query_one("#rate-limit-banner", Static)
        except Exception:
            return
        rate_limited = bool(data.get("rate_limited"))
        if rate_limited:
            detail = str(data.get("error") or "HTTP 429 Too Many Requests")
            banner.update(
                escape_markup(
                    f"⚠ GROQ RATE LIMIT — {detail}. Wait for retry-after; distill falls back to rules."
                )
            )
            banner.add_class("visible")
        else:
            banner.update("")
            banner.remove_class("visible")

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
            ("Last", str(data.get("last_import_status", "none")), "muted"),
        ])

    # --- MCP doctor (shared brain wiring) ---

    @work(thread=True, group="mcp-doctor", exit_on_error=False)
    def _load_mcp_doctor(self) -> dict[str, Any]:
        try:
            from brainkm.services.mcp_doctor import build_mcp_doctor_report
            from brainkm.tui.mcp_doctor_view import mcp_doctor_panel_items

            report = build_mcp_doctor_report(self._project_dir)
            return {"items": mcp_doctor_panel_items(report)}
        except Exception as exc:
            return {"error": str(exc), "items": [("Status", str(exc)[:60], "error")]}

    def _render_mcp_doctor(self, data: dict[str, Any]) -> None:
        panel = self.query_one("#mcp-doctor-panel", StatusPanel)
        items = data.get("items")
        if isinstance(items, list) and items:
            panel.set_items([(str(a), str(b), str(c)) for a, b, c in items])
            return
        err = data.get("error") or "doctor unavailable"
        panel.set_items([("Status", str(err)[:60], "error")])

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
        except Exception as exc:
            return [{"__error__": str(exc)}]

    def _render_review_status(self, items: list[dict]) -> None:
        if items and isinstance(items[0], dict) and items[0].get("__error__"):
            err = str(items[0]["__error__"])
            self.notify(
                escape_markup(f"Review queue unavailable: {err}"),
                severity="warning",
                timeout=5,
            )
            items = []
        self._pending_review_count = len(items)
        self._render_brain_status()
        title = self.query_one("#review-title", Static)
        hint = self.query_one("#review-hint", Static)
        title.update(escape_markup(f"REVIEW QUEUE ({len(items)})"))
        if items:
            hint.update(
                escape_markup("! ACTION REQUIRED — Enter detail · y approve / n reject")
            )
        else:
            hint.update(
                escape_markup(
                    "Low-confidence auto-captures wait here — Enter detail · y approve / n reject"
                )
            )

        section = self.query_one("#review-section")
        if items:
            section.remove_class("review-section--empty")
        else:
            section.add_class("review-section--empty")

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
            "btn-mcp-doctor-refresh": self._load_mcp_doctor,
            "btn-start-serve": self._run_start_serve,
            "btn-stop-serve": self._run_stop_serve,
        }
        handler = handlers.get(event.button.id or "")
        if handler:
            handler()

    def _run_start_serve(self) -> None:
        self.notify("Starting shared brain…", severity="information")
        self._do_start_serve()

    def _run_stop_serve(self) -> None:
        self.notify("Stopping shared brain…", severity="information")
        self._do_stop_serve()

    @work(thread=True, group="dashboard-action", exit_on_error=False)
    def _do_start_serve(self) -> dict[str, Any]:
        from brainkm.services.serve_helper import start_serve_background

        try:
            status = start_serve_background(self._project_dir, dev=True)
            return {
                "action": "start_serve",
                "ok": status.running,
                "url": status.health_url,
                "error": None if status.running else status.detail,
            }
        except Exception as exc:
            return {"action": "start_serve", "ok": False, "error": str(exc)}

    @work(thread=True, group="dashboard-action", exit_on_error=False)
    def _do_stop_serve(self) -> dict[str, Any]:
        from brainkm.services.serve_helper import stop_serve_background

        try:
            stop_serve_background(self._project_dir)
            return {"action": "stop_serve", "ok": True}
        except Exception as exc:
            return {"action": "stop_serve", "ok": False, "error": str(exc)}

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

    def on_review_table_detail_requested(self, event: ReviewTable.DetailRequested) -> None:
        self._open_review_detail(event.item)

    def _open_review_detail(self, item: dict) -> None:
        from brainkm.tui.widgets.review_detail_modal import ReviewDetailModal

        node_id = str(item.get("node_id") or "")
        if not node_id:
            return

        def _after_detail(action: str | None) -> None:
            if action == "approve":
                self._approve_review_item(node_id)
            elif action == "reject":
                self._reject_review_item(node_id)

        self.app.push_screen(
            ReviewDetailModal(
                node_id=node_id,
                project_dir=self._project_dir,
                title=str(item.get("title") or ""),
                subtype=str(item.get("subtype") or ""),
                confidence=float(item.get("confidence") or 0.0),
            ),
            _after_detail,
        )

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

    _PANEL_FOR_GROUP: dict[str, str] = {
        "brain-status": "#brain-status",
        "ollama-status": "#ollama-panel",
        "groq-status": "#groq-panel",
        "graph-status": "#graph-panel",
        "serve-status": "#serve-status",
        "mcp-doctor": "#mcp-doctor-panel",
    }

    def _on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle worker completion for all status loads and actions."""
        worker = event.worker
        if event.state == WorkerState.ERROR:
            err = event.worker.error
            msg = escape_markup(str(err) if err else "unknown error")
            panel_id = self._PANEL_FOR_GROUP.get(worker.group or "")
            if panel_id:
                try:
                    self.query_one(panel_id, StatusPanel).set_error(str(err)[:72])
                except Exception:
                    pass
            if worker.group == "review-status":
                self.notify(f"Review load failed: {msg}", severity="error", timeout=6)
            elif worker.group in {"review-action", "dashboard-action"}:
                self.notify(f"Action failed: {msg}", severity="error", timeout=6)
            elif panel_id:
                self.notify(f"Status load failed: {msg}", severity="warning", timeout=5)
            return
        if event.state != WorkerState.SUCCESS:
            return
        if worker.group == "brain-status":
            self._render_brain_status(worker.result)
            self._update_header_health()
        elif worker.group == "ollama-status":
            self._render_ollama_status(worker.result)
            self._update_header_health()
        elif worker.group == "groq-status":
            self._render_groq_status(worker.result)
            self._update_header_health()
        elif worker.group == "graph-status":
            self._render_graph_status(worker.result)
            self._update_header_health()
        elif worker.group == "serve-status":
            self._render_serve_status(worker.result)
        elif worker.group == "mcp-doctor":
            self._render_mcp_doctor(worker.result)
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

    def _update_header_health(self) -> None:
        """Readable counts in the Header subtitle (details live on the Dashboard)."""
        app = self.app
        update = getattr(app, "update_header_subtitle", None)
        if not callable(update):
            return
        parts: list[str] = []
        neurons = self._last_brain_data.get("neuron_count")
        if neurons is not None:
            parts.append(f"{neurons} neurons")
        code = self._last_brain_data.get("code_node_count")
        if code is not None:
            parts.append(f"{code} code nodes")
        # Ollama / Groq / graph freshness already appear in Dashboard panels —
        # omit cryptic header glyphs (O✓ Q✓ ◆) that were hard to read.
        update(" · ".join(parts) if parts else None)

    def _handle_dashboard_action(self, result: dict[str, Any]) -> None:
        action = result.get("action", "")
        if not result.get("ok"):
            detail = result.get("error") or result.get("message") or "failed"
            self.notify(escape_markup(f"{action}: {detail}"), severity="error")
            if action in {"start_serve", "stop_serve"}:
                self._load_serve_status()
            return

        if action == "ollama_apply":
            self.notify("Ollama model applied", severity="information")
            self._load_ollama_status()
            self._load_brain_status()
        elif action == "start_serve":
            self.notify("Shared brain running", severity="information")
            self._load_serve_status()
        elif action == "stop_serve":
            self.notify("Shared brain stopped", severity="information")
            self._load_serve_status()
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

    def action_review_detail(self) -> None:
        table = self.query_one("#review-table", ReviewTable)
        item = table.get_selected_item()
        if item:
            self._open_review_detail(item)
