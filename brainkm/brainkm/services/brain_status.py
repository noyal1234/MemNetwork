"""Dashboard brain-status summary (TUI sidebar).

Keeps SQL and distill probes out of the Textual layer — MCP / CLI / TUI all
go through services.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_brain_status_summary(project_dir: Path | None = None) -> dict[str, Any]:
    """Return sidebar fields for the configure dashboard.

    Keys:
      distill_mode, distill_display, distill_color,
      neuron_count, code_node_count, edge_count, db_size,
      auto_observe, mcp_transport,
      commit_trace, commit_trace_label, commit_trace_color
    """
    result: dict[str, Any] = {}
    try:
        from brainkm.services.config_loader import (
            load_brain_config,
            raw_config_has_commit_trace,
            should_install_commit_hook,
        )
        from brainkm.services.distill_status import (
            active_distill_display,
            build_distill_status,
        )
        from brainkm.services.git_note import (
            detect_external_hook_manager,
            post_commit_hook_installed,
        )
        from brainkm.services.install import resolve_project_dir

        root = resolve_project_dir(project_dir)
        cfg = load_brain_config(root)
        result["distill_mode"] = cfg.capture.distill_mode
        result["auto_observe"] = bool(cfg.capture.auto_observe)
        result["mcp_transport"] = str(cfg.mcp.transport)
        statuses = build_distill_status(project_dir=root)
        _mode, display, color = active_distill_display(statuses)
        result["distill_display"] = display
        result["distill_color"] = color

        want_hook = should_install_commit_hook(root, cfg)
        hook_on_disk = post_commit_hook_installed(root)
        external = detect_external_hook_manager(root)
        explicit = raw_config_has_commit_trace(root)
        result["commit_trace"] = want_hook
        result["commit_trace_hook_installed"] = hook_on_disk
        if want_hook and hook_on_disk:
            result["commit_trace_label"] = "on"
            result["commit_trace_color"] = "ok"
        elif want_hook and external:
            result["commit_trace_label"] = "skipped"
            result["commit_trace_color"] = "warning"
        elif want_hook and not hook_on_disk:
            result["commit_trace_label"] = "on · no hook"
            result["commit_trace_color"] = "warning"
        elif not explicit and Path(root / ".brain" / "config.json").is_file():
            result["commit_trace_label"] = "off"
            result["commit_trace_color"] = "muted"
        else:
            result["commit_trace_label"] = "off"
            result["commit_trace_color"] = "muted"
    except Exception as exc:
        result["distill_mode"] = "unknown"
        result["distill_display"] = "unknown"
        result["distill_color"] = "muted"
        result["distill_error"] = str(exc)
        result["auto_observe"] = False
        result["mcp_transport"] = "?"
        result["commit_trace"] = False
        result["commit_trace_label"] = "?"
        result["commit_trace_color"] = "muted"
        result["commit_trace_error"] = str(exc)

    try:
        from brainkm.db.connection import connect
        from brainkm.db.paths import brain_db_path
        from brainkm.services.channel_health import graph_counts

        db_path = brain_db_path(project_dir)
        size_kb = db_path.stat().st_size / 1024
        if size_kb >= 1024:
            result["db_size"] = f"{size_kb / 1024:.1f} MB"
        else:
            result["db_size"] = f"{size_kb:.0f} KB"
        conn = connect(db_path)
        try:
            row = conn.execute(
                "SELECT COUNT(*) as c FROM nodes "
                "WHERE kind='memory' AND valid_until IS NULL"
            ).fetchone()
            result["neuron_count"] = row["c"] if row else 0
            code_nodes, edges = graph_counts(conn)
            result["code_node_count"] = code_nodes
            result["edge_count"] = edges
        finally:
            conn.close()
    except Exception as exc:
        result["db_size"] = "n/a"
        result["neuron_count"] = 0
        result["code_node_count"] = 0
        result["edge_count"] = 0
        result["db_error"] = str(exc)

    return result
