"""Helpers to start/check the shared localhost brain server (for TUI / non-CLI users)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from brainkm.services.config_loader import load_brain_config
from brainkm.services.install import resolve_hook_command, resolve_project_dir
from brainkm.services.mcp_doctor import probe_health
from brainkm.services.mcp_transport import mcp_health_url


@dataclass(frozen=True)
class ServeStatus:
    running: bool
    health_url: str
    detail: str
    transport: str
    pid_file: Path


def serve_pid_path(project_dir: Path | None = None) -> Path:
    root = resolve_project_dir(project_dir)
    return root / ".brain" / "serve.pid"


def get_serve_status(project_dir: Path | None = None) -> ServeStatus:
    root = resolve_project_dir(project_dir)
    cfg = load_brain_config(root)
    url = mcp_health_url(host=cfg.mcp.http_host, port=cfg.mcp.http_port)
    ok, detail = probe_health(host=cfg.mcp.http_host, port=cfg.mcp.http_port)
    return ServeStatus(
        running=ok,
        health_url=url,
        detail=detail,
        transport=cfg.mcp.transport,
        pid_file=serve_pid_path(root),
    )


def start_serve_background(
    project_dir: Path | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
    dev: bool = True,
) -> ServeStatus:
    """Start ``brainkm serve`` detached; idempotent if already healthy."""
    root = resolve_project_dir(project_dir)
    cfg = load_brain_config(root)
    resolved_host = host or cfg.mcp.http_host
    resolved_port = port or cfg.mcp.http_port

    current = get_serve_status(root)
    if current.running:
        return current

    allow_remote = bool(cfg.mcp.allow_remote)
    brainkm_bin = resolve_hook_command(dev=dev)
    cmd = [
        brainkm_bin,
        "serve",
        "--project-dir",
        str(root),
        "--host",
        resolved_host,
        "--port",
        str(resolved_port),
    ]
    if allow_remote:
        cmd.append("--allow-remote")
    # Fall back to python -m if binary missing.
    if not Path(brainkm_bin).exists() and brainkm_bin == "brainkm":
        cmd = [
            sys.executable,
            "-m",
            "brainkm.cli",
            "serve",
            "--project-dir",
            str(root),
            "--host",
            resolved_host,
            "--port",
            str(resolved_port),
        ]
        if allow_remote:
            cmd.append("--allow-remote")

    log_path = root / ".brain" / "serve.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_f = log_path.open("a", encoding="utf-8")
    proc = subprocess.Popen(  # noqa: S603
        cmd,
        stdout=log_f,
        stderr=subprocess.STDOUT,
        cwd=str(root),
        start_new_session=True,
    )
    serve_pid_path(root).write_text(str(proc.pid), encoding="utf-8")
    # Brief settle — health may take a moment.
    import time

    for _ in range(10):
        time.sleep(0.2)
        status = get_serve_status(root)
        if status.running:
            return status
    return get_serve_status(root)


def stop_serve_background(project_dir: Path | None = None) -> bool:
    """Stop a serve process started via pid file. Returns True if a signal was sent."""
    root = resolve_project_dir(project_dir)
    pid_file = serve_pid_path(root)
    if not pid_file.is_file():
        return False
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except ValueError:
        pid_file.unlink(missing_ok=True)
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pid_file.unlink(missing_ok=True)
        return False
    pid_file.unlink(missing_ok=True)
    return True
