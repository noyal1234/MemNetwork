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
      neuron_count, code_node_count, db_size
    """
    result: dict[str, Any] = {}
    try:
        from brainkm.services.config_loader import load_brain_config
        from brainkm.services.distill_status import (
            active_distill_display,
            build_distill_status,
        )

        cfg = load_brain_config(project_dir)
        result["distill_mode"] = cfg.capture.distill_mode
        statuses = build_distill_status(project_dir=project_dir)
        _mode, display, color = active_distill_display(statuses)
        result["distill_display"] = display
        result["distill_color"] = color
    except Exception as exc:
        result["distill_mode"] = "unknown"
        result["distill_display"] = "unknown"
        result["distill_color"] = "muted"
        result["distill_error"] = str(exc)

    try:
        from brainkm.db.connection import connect
        from brainkm.db.paths import brain_db_path

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
            code_row = conn.execute(
                "SELECT COUNT(*) as c FROM nodes WHERE kind='code'"
            ).fetchone()
            result["code_node_count"] = code_row["c"] if code_row else 0
        finally:
            conn.close()
    except Exception as exc:
        result["db_size"] = "n/a"
        result["neuron_count"] = 0
        result["code_node_count"] = 0
        result["db_error"] = str(exc)

    return result
