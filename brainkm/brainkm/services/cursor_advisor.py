"""Cursor agent CLI diagnostics for distill readiness."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from brainkm.adapters.cursor_distill import resolve_cursor_agent_bin
from brainkm.logging_config import get_logger
from brainkm.services.config_loader import config_path, load_brain_config

logger = get_logger("services.cursor_advisor")

HEURISTIC_HINT = (
    "cursor mode always works offline via Cursor-aware heuristic distill; "
    "install the Cursor agent CLI (agent / cursor-agent) for optional LLM-quality extraction"
)


@dataclass(frozen=True)
class CursorStatus:
    found: bool
    bin_path: str | None = None
    bin_name: str | None = None


@dataclass(frozen=True)
class CursorDoctorReport:
    status: CursorStatus
    distill_mode: str | None
    config_path: Path | None
    heuristic_hint: str = HEURISTIC_HINT


def probe_cursor_agent() -> CursorStatus:
    """Locate the Cursor agent CLI on PATH (agent or cursor-agent)."""
    path = resolve_cursor_agent_bin()
    if not path:
        return CursorStatus(found=False)
    name = Path(path).name
    return CursorStatus(found=True, bin_path=path, bin_name=name)


def build_cursor_doctor_report(
    *,
    project_dir: Path | None = None,
) -> CursorDoctorReport:
    """Assemble Cursor agent CLI and distill-mode status."""
    cfg_path = config_path(project_dir)
    distill_mode: str | None = None
    if cfg_path.is_file():
        cfg = load_brain_config(project_dir)
        distill_mode = cfg.capture.distill_mode

    status = probe_cursor_agent()
    return CursorDoctorReport(
        status=status,
        distill_mode=distill_mode,
        config_path=cfg_path if cfg_path.is_file() else None,
    )


def format_cursor_report(report: CursorDoctorReport) -> str:
    """Render Cursor doctor output for CLI / TUI."""
    lines: list[str] = []
    if report.status.found:
        lines.append(
            f"Cursor agent CLI: found ({report.status.bin_name} -> {report.status.bin_path})"
        )
        lines.append("LLM-quality Cursor distill: available when distill_mode is cursor")
    else:
        lines.append("Cursor agent CLI: not found (agent / cursor-agent not on PATH)")
        lines.append("LLM-quality Cursor distill: unavailable — heuristic distill will be used")

    if report.distill_mode is None:
        lines.append("Config distill_mode: (no .brain/config.json)")
    else:
        lines.append(f"Config distill_mode: {report.distill_mode}")

    lines.append(f"Hint: {report.heuristic_hint}")
    lines.append(
        'To use Cursor distill: set capture.distill_mode to "cursor" in .brain/config.json'
    )
    return "\n".join(lines)
