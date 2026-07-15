"""Unified distill-mode readiness status for CLI and TUI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from brainkm.config import get_settings
from brainkm.logging_config import get_logger
from brainkm.services.config_loader import config_path, load_brain_config
from brainkm.services.cursor_advisor import probe_cursor_agent
from brainkm.services.groq_advisor import probe_groq
from brainkm.services.ollama_advisor import probe_ollama

logger = get_logger("services.distill_status")

# Backend / doctor order (rules remains a real mode + timeout fallback).
DISTILL_MODES = ("cursor", "rules", "ollama", "groq", "mcp")

# Primary TUI pickers: rules is intentionally omitted — it overlaps conceptually
# with cursor heuristics and is an advanced/offline fallback, not a peer choice.
PRIMARY_DISTILL_MODES = ("cursor", "ollama", "groq", "mcp")

# User-facing labels: cursor must not say "rule-based" (that collides with rules).
DISTILL_MODE_LABELS: dict[str, str] = {
    "cursor": (
        "cursor — Cursor transcripts (default; free heuristic, "
        "optional Agent CLI for LLM quality)"
    ),
    "rules": "rules — advanced raw pattern fallback (no Cursor cleanup)",
    "ollama": "ollama — local LLM (needs Ollama daemon)",
    "groq": "groq — cloud LLM (needs GROQ_API_KEY)",
    "mcp": "mcp — client model via MCP sampling (falls back to rules)",
}


def distill_mode_select_options(
    *,
    include_rules: bool = False,
    current: str | None = None,
) -> list[tuple[str, str]]:
    """(label, value) pairs for Config/Wizard pickers."""
    modes: list[str] = list(PRIMARY_DISTILL_MODES)
    if include_rules or current == "rules":
        # Keep advanced mode visible only when already selected in config.
        if "rules" not in modes:
            modes.insert(1, "rules")
    return [(DISTILL_MODE_LABELS[m], m) for m in modes]


@dataclass(frozen=True)
class DistillModeStatus:
    mode: str
    ready: bool
    detail: str
    is_default: bool
    is_active: bool = False


def build_distill_status(
    *,
    project_dir: Path | None = None,
) -> list[DistillModeStatus]:
    """Probe all distill backends and return one status row per mode.

    - rules  — always ready (pure pattern match)
    - cursor — always ready (heuristic fallback); detail notes agent CLI
    - ollama — ready when daemon is reachable
    - groq   — ready when API key works and endpoint is reachable
    """
    cfg_path = config_path(project_dir)
    active_mode = "cursor"
    ollama_base = "http://127.0.0.1:11434"
    groq_base = "https://api.groq.com/openai/v1"
    groq_model: str | None = None
    if cfg_path.is_file():
        try:
            cfg = load_brain_config(project_dir)
            active_mode = cfg.capture.distill_mode
            ollama_base = cfg.ollama.base_url
            groq_base = cfg.groq.base_url
            groq_model = cfg.groq.model
        except Exception as exc:
            logger.debug("distill_status: config load failed: %s", exc)

    cursor = probe_cursor_agent()
    ollama = probe_ollama(ollama_base)
    groq = probe_groq(groq_base, get_settings().groq_api_key, model=groq_model)

    statuses: list[DistillModeStatus] = [
        DistillModeStatus(
            mode="cursor",
            ready=True,
            detail=(
                f"agent CLI ({cursor.bin_name})"
                if cursor.found
                else "heuristic active (no agent CLI)"
            ),
            is_default=True,
            is_active=active_mode == "cursor",
        ),
        DistillModeStatus(
            mode="rules",
            ready=True,
            detail="pattern-match offline",
            is_default=False,
            is_active=active_mode == "rules",
        ),
        DistillModeStatus(
            mode="ollama",
            ready=ollama.reachable,
            detail="connected" if ollama.reachable else "unreachable",
            is_default=False,
            is_active=active_mode == "ollama",
        ),
        DistillModeStatus(
            mode="groq",
            ready=groq.reachable,
            detail=(
                "connected"
                if groq.reachable
                else (groq.error or "unreachable")
            ),
            is_default=False,
            is_active=active_mode == "groq",
        ),
        DistillModeStatus(
            mode="mcp",
            ready=True,
            detail="uses host sampling when available; else rules",
            is_default=False,
            is_active=active_mode == "mcp",
        ),
    ]
    return statuses


def format_distill_status_line(statuses: list[DistillModeStatus]) -> str:
    """Compact one-line summary for Config Editor / Dashboard.

    Omits inactive ``rules`` so readiness does not look like a third peer
    beside cursor (rules is an advanced fallback, not a primary distill choice).
    """
    parts: list[str] = []
    for item in statuses:
        if item.mode == "rules" and not item.is_active:
            continue
        mark = "OK" if item.ready else "unreachable"
        if item.mode in ("cursor", "rules") and item.ready:
            mark = "OK"
        if not item.ready and item.mode == "groq" and item.detail:
            # Prefer short detail for groq failures (e.g. "GROQ_API_KEY not set")
            short = item.detail.split("(")[0].strip()
            mark = short if len(short) < 40 else "unreachable"
        elif not item.ready:
            mark = "unreachable"
        elif item.mode == "cursor":
            mark = item.detail if "heuristic" in item.detail else "OK"
        parts.append(f"{item.mode} {mark}")
    return " | ".join(parts)


def active_distill_display(
    statuses: list[DistillModeStatus],
) -> tuple[str, str, str]:
    """Return (mode, display_value, color_class) for the active distill mode."""
    active = next((s for s in statuses if s.is_active), None)
    if active is None and statuses:
        active = statuses[0]
    if active is None:
        return ("?", "unknown", "muted")
    color = "ok" if active.ready else "error"
    if active.mode == "cursor" and "heuristic" in active.detail:
        color = "ok"
    display = f"{active.mode} ({active.detail})"
    return (active.mode, display, color)
