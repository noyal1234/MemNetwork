"""Claude Code CLI diagnostics and optional install for wizard setup."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from brainkm.adapters.claude_distill import resolve_claude_bin
from brainkm.logging_config import get_logger

logger = get_logger("services.claude_advisor")

NPM_INSTALL_HINT = "npm install -g @anthropic-ai/claude-code"
DEFAULT_INSTALL_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class ClaudeCliStatus:
    found: bool
    bin_path: str | None = None


@dataclass(frozen=True)
class ClaudeCliInstallResult:
    ok: bool
    found: bool
    bin_path: str | None = None
    stdout_tail: str = ""
    error: str | None = None


def probe_claude_cli() -> ClaudeCliStatus:
    """Locate the `claude` CLI on PATH."""
    path = resolve_claude_bin()
    if not path:
        return ClaudeCliStatus(found=False)
    return ClaudeCliStatus(found=True, bin_path=path)


def format_claude_cli_report(status: ClaudeCliStatus) -> str:
    """Render Claude CLI doctor output for the wizard."""
    if status.found:
        return f"Claude Code CLI: found ({status.bin_path})"
    return (
        "Claude Code CLI: not found (claude not on PATH)\n"
        f"Install with: {NPM_INSTALL_HINT}"
    )


def install_claude_cli(
    *,
    timeout_seconds: int = DEFAULT_INSTALL_TIMEOUT_SECONDS,
) -> ClaudeCliInstallResult:
    """Install the Claude Code CLI globally via npm, then re-probe.

    User-initiated only (Wizard Run Step). Never call on mount.
    """
    existing = probe_claude_cli()
    if existing.found:
        return ClaudeCliInstallResult(
            ok=True,
            found=True,
            bin_path=existing.bin_path,
            stdout_tail="already installed",
        )

    if not shutil.which("npm"):
        return ClaudeCliInstallResult(
            ok=False,
            found=False,
            error=f"npm not found on PATH — install Node.js, then run: {NPM_INSTALL_HINT}",
        )

    logger.info("Installing Claude Code CLI via npm")
    try:
        completed = subprocess.run(
            ["npm", "install", "-g", "@anthropic-ai/claude-code"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ClaudeCliInstallResult(
            ok=False,
            found=False,
            error=f"install timed out after {timeout_seconds}s",
        )
    except OSError as exc:
        return ClaudeCliInstallResult(ok=False, found=False, error=str(exc))

    combined = "\n".join(
        part for part in (completed.stdout or "", completed.stderr or "") if part
    ).strip()
    tail = combined[-1500:] if combined else ""

    status = probe_claude_cli()
    if status.found:
        return ClaudeCliInstallResult(
            ok=True,
            found=True,
            bin_path=status.bin_path,
            stdout_tail=tail,
        )

    error = f"install exited {completed.returncode}"
    if completed.returncode != 0 and tail:
        error = f"{error}: {tail[-300:]}"
    elif not status.found:
        error = f"{error}; claude not found on PATH after install"
    return ClaudeCliInstallResult(
        ok=False,
        found=False,
        stdout_tail=tail,
        error=error,
    )
