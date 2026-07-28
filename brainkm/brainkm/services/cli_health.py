"""CLI / launcher health breadcrumbs (``.brain/cli_health.json``).

Written by ``scripts/brainkm_launcher.py`` (stdlib-only) when macOS UF_HIDDEN
breaks editable imports or when a heal re-exec clears ``*.pth`` flags.
Consumed by SessionStart (user-visible pack notice) and ``brainkm doctor``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from brainkm.db.paths import brain_dir

CLI_HEALTH_FILENAME = "cli_health.json"
_UF_HIDDEN = 0x8000


def cli_health_path(project_dir: Path | None = None) -> Path:
    return brain_dir(project_dir) / CLI_HEALTH_FILENAME


def read_cli_health(project_dir: Path | None = None) -> dict[str, Any] | None:
    path = cli_health_path(project_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def clear_cli_health(project_dir: Path | None = None) -> None:
    path = cli_health_path(project_dir)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def consume_cli_health_notice(project_dir: Path | None = None) -> str | None:
    """Return a one-shot user-facing notice and clear the breadcrumb.

    ``healed`` → session recovered after auto-clearing hidden .pth flags.
    ``broken`` → last launcher attempt failed (should be rare if SessionStart runs).
    """
    data = read_cli_health(project_dir)
    if not data:
        return None
    status = str(data.get("status") or "").strip().lower()
    fix = str(data.get("fix") or "bash brainkm/scripts/repair_venv.sh")
    cleared = int(data.get("cleared_pth") or 0)
    clear_cli_health(project_dir)
    if status == "healed":
        extra = f" (cleared {cleared} .pth file(s))" if cleared else ""
        return (
            f"brainkm: auto-repaired macOS hidden .venv editable install{extra}. "
            f"If hooks fail again, run: {fix}"
        )
    if status == "broken":
        err = str(data.get("error") or "CLI import failed").strip()
        return f"brainkm: CLI was broken on a prior launch ({err}). Fix: {fix}"
    return None


def hidden_editable_pth_count(project_dir: Path | None = None) -> int:
    """Count ``*.pth`` under ``.venv`` that still carry UF_HIDDEN (Darwin only)."""
    import os
    import sys

    if sys.platform != "darwin":
        return 0
    root = project_dir if project_dir is not None else Path.cwd()
    venv = root / ".venv"
    if not venv.is_dir():
        return 0
    count = 0
    for pth in venv.glob("lib/python*/site-packages/*.pth"):
        try:
            flags = getattr(os.stat(pth), "st_flags", 0)
        except OSError:
            continue
        if flags & _UF_HIDDEN:
            count += 1
    return count


def doctor_cli_health_notes(project_dir: Path | None = None) -> list[str]:
    """Notes for ``brainkm doctor`` about launcher / UF_HIDDEN health."""
    notes: list[str] = []
    data = read_cli_health(project_dir)
    if data and str(data.get("status") or "").lower() == "broken":
        fix = data.get("fix") or "bash brainkm/scripts/repair_venv.sh"
        notes.append(
            f"WARNING: brainkm CLI import breadcrumb is broken — run `{fix}` "
            "(SessionStart/hooks may be exiting silently)"
        )
    hidden = hidden_editable_pth_count(project_dir)
    if hidden:
        notes.append(
            f"WARNING: {hidden} .venv *.pth file(s) marked UF_HIDDEN — Python 3.12+ "
            "skips them; run `bash brainkm/scripts/repair_venv.sh` "
            "(launcher also auto-clears on next brainkm invoke)"
        )
    return notes
