"""Cursor agent CLI diagnostics and optional install for distill readiness."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
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

CURSOR_INSTALL_URL = "https://cursor.com/install"
DEFAULT_INSTALL_TIMEOUT_SECONDS = 300


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


@dataclass(frozen=True)
class CursorInstallResult:
    ok: bool
    found: bool
    bin_path: str | None = None
    stdout_tail: str = ""
    error: str | None = None


def local_bin_dir() -> Path:
    return Path.home() / ".local" / "bin"


def ensure_cursor_agent_path() -> bool:
    """Prepend ~/.local/bin to PATH for this process if present and missing.

    Returns True when the directory is now on PATH (already was, or just added).
    """
    local = local_bin_dir()
    if not local.is_dir():
        return False

    local_str = str(local)
    current = os.environ.get("PATH", "")
    parts = current.split(os.pathsep) if current else []
    if local_str in parts:
        return True

    os.environ["PATH"] = local_str + (os.pathsep + current if current else "")
    logger.debug("Prepended %s to PATH for Cursor agent discovery", local_str)
    return True


def probe_cursor_agent() -> CursorStatus:
    """Locate the Cursor agent CLI on PATH or under ~/.local/bin."""
    ensure_cursor_agent_path()
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


def _download_cursor_install_script(dest: Path, *, timeout_seconds: int) -> None:
    """Download the allowlisted Cursor install script to *dest*."""
    request = urllib.request.Request(
        CURSOR_INSTALL_URL,
        headers={"User-Agent": "brainkm-cursor-advisor"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as resp:  # noqa: S310
        dest.write_bytes(resp.read())


def install_cursor_agent_cli(
    *,
    timeout_seconds: int = DEFAULT_INSTALL_TIMEOUT_SECONDS,
) -> CursorInstallResult:
    """Download and run the official Cursor agent install script, then re-probe.

    User-initiated only (CLI / Wizard Run Step). Never call on mount.
    Uses urllib download + ``bash <script>`` (no ``shell=True``).
    """
    if not shutil.which("bash"):
        return CursorInstallResult(
            ok=False,
            found=False,
            error="bash not found on PATH — required for the official installer",
        )

    # Already present — no network install needed.
    existing = probe_cursor_agent()
    if existing.found:
        return CursorInstallResult(
            ok=True,
            found=True,
            bin_path=existing.bin_path,
            stdout_tail="already installed",
        )

    logger.info("Installing Cursor agent CLI via official install script")
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix="-cursor-install.sh",
            delete=False,
        ) as tmp:
            script_path = Path(tmp.name)
        try:
            _download_cursor_install_script(script_path, timeout_seconds=timeout_seconds)
            completed = subprocess.run(
                ["bash", str(script_path)],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        finally:
            script_path.unlink(missing_ok=True)
    except urllib.error.URLError as exc:
        return CursorInstallResult(
            ok=False,
            found=False,
            error=f"failed to download installer: {exc}",
        )
    except subprocess.TimeoutExpired:
        return CursorInstallResult(
            ok=False,
            found=False,
            error=f"install timed out after {timeout_seconds}s",
        )
    except OSError as exc:
        return CursorInstallResult(ok=False, found=False, error=str(exc))

    combined = "\n".join(
        part for part in (completed.stdout or "", completed.stderr or "") if part
    ).strip()
    tail = combined[-1500:] if combined else ""

    ensure_cursor_agent_path()
    status = probe_cursor_agent()
    if status.found:
        return CursorInstallResult(
            ok=True,
            found=True,
            bin_path=status.bin_path,
            stdout_tail=tail,
        )

    error = f"install exited {completed.returncode}"
    if completed.returncode != 0 and tail:
        error = f"{error}: {tail[-300:]}"
    elif not status.found:
        error = (
            f"{error}; agent not found after install "
            "(add ~/.local/bin to your shell PATH and retry)"
        )
    return CursorInstallResult(
        ok=False,
        found=False,
        stdout_tail=tail,
        error=error,
    )
