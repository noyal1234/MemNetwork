"""Helpers to start/check the shared localhost brain server (for TUI / non-CLI users)."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from brainkm import __version__ as PACKAGE_VERSION
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
    serve_version: str | None = None
    package_version: str = PACKAGE_VERSION
    version_mismatch: bool = False


def serve_pid_path(project_dir: Path | None = None) -> Path:
    root = resolve_project_dir(project_dir)
    return root / ".brain" / "serve.pid"


def parse_health_version(detail: str) -> str | None:
    """Extract ``version`` from a ``/health`` JSON body (best-effort)."""
    text = (detail or "").strip()
    if not text.startswith("{"):
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    ver = payload.get("version")
    return str(ver).strip() if ver is not None and str(ver).strip() else None


def get_serve_status(project_dir: Path | None = None) -> ServeStatus:
    """Report whether *this project's* shared HTTP brain is up.

    Stdio projects do not probe the default localhost port — another project's
    ``brainkm serve`` on :8765 must not look like this brain is running. Probe
    only when transport is ``http``, or when ``.brain/serve.pid`` exists (TUI
    Start Brain may launch HTTP while config is still settling).
    """
    root = resolve_project_dir(project_dir)
    cfg = load_brain_config(root)
    url = mcp_health_url(host=cfg.mcp.http_host, port=cfg.mcp.http_port)
    pid_file = serve_pid_path(root)
    transport = cfg.mcp.transport
    if transport != "http" and not pid_file.is_file():
        return ServeStatus(
            running=False,
            health_url=url,
            detail="stdio transport (no shared HTTP serve)",
            transport=transport,
            pid_file=pid_file,
            package_version=PACKAGE_VERSION,
        )
    ok, detail = probe_health(host=cfg.mcp.http_host, port=cfg.mcp.http_port)
    serve_ver = parse_health_version(detail) if ok else None
    mismatch = bool(
        ok and serve_ver is not None and serve_ver != PACKAGE_VERSION
    )
    return ServeStatus(
        running=ok,
        health_url=url,
        detail=detail,
        transport=transport,
        pid_file=pid_file,
        serve_version=serve_ver,
        package_version=PACKAGE_VERSION,
        version_mismatch=mismatch,
    )


def _build_serve_cmd(
    root: Path,
    *,
    host: str,
    port: int,
    allow_remote: bool,
    dev: bool,
) -> list[str]:
    brainkm_bin = resolve_hook_command(dev=dev)
    cmd = [
        brainkm_bin,
        "serve",
        "--project-dir",
        str(root),
        "--host",
        host,
        "--port",
        str(port),
    ]
    if allow_remote:
        cmd.append("--allow-remote")
    if not Path(brainkm_bin).exists() and brainkm_bin == "brainkm":
        cmd = [
            sys.executable,
            "-m",
            "brainkm.cli",
            "serve",
            "--project-dir",
            str(root),
            "--host",
            host,
            "--port",
            str(port),
        ]
        if allow_remote:
            cmd.append("--allow-remote")
    return cmd


def start_serve_background(
    project_dir: Path | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
    dev: bool = True,
    force: bool = False,
) -> ServeStatus:
    """Start ``brainkm serve`` detached.

    Idempotent if already healthy and versions match. Pass ``force=True`` (or use
    ``restart_serve_background``) to replace a stale/mismatched process.
    """
    root = resolve_project_dir(project_dir)
    cfg = load_brain_config(root)
    resolved_host = host or cfg.mcp.http_host
    resolved_port = port or cfg.mcp.http_port

    current = get_serve_status(root)
    if current.running and not force and not current.version_mismatch:
        return current
    if current.running and (force or current.version_mismatch):
        stop_serve_background(root)
        _wait_until_stopped(root, timeout_s=3.0)

    allow_remote = bool(cfg.mcp.allow_remote)
    cmd = _build_serve_cmd(
        root,
        host=resolved_host,
        port=resolved_port,
        allow_remote=allow_remote,
        dev=dev,
    )

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
    for _ in range(15):
        time.sleep(0.2)
        status = get_serve_status(root)
        if status.running and not status.version_mismatch:
            return status
        if status.running and status.serve_version is None:
            return status
    return get_serve_status(root)


def _pids_on_port(port: int) -> list[int]:
    """Best-effort listener PIDs for ``port`` (lsof). Empty when unavailable."""
    try:
        proc = subprocess.run(  # noqa: S603
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    pids: list[int] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids


def _wait_until_stopped(root: Path, *, timeout_s: float = 3.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not get_serve_status(root).running:
            return
        time.sleep(0.15)


def stop_serve_background(project_dir: Path | None = None) -> bool:
    """Stop shared HTTP serve (pid file and/or port listeners).

    Returns True if any SIGTERM was sent.
    """
    root = resolve_project_dir(project_dir)
    cfg = load_brain_config(root)
    signaled = False
    pid_file = serve_pid_path(root)
    if pid_file.is_file():
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
        except ValueError:
            pid_file.unlink(missing_ok=True)
        else:
            try:
                os.kill(pid, signal.SIGTERM)
                signaled = True
            except ProcessLookupError:
                pass
            pid_file.unlink(missing_ok=True)

    # Cover serves started outside the TUI (no pid file) or stale pid files.
    for pid in _pids_on_port(int(cfg.mcp.http_port)):
        try:
            os.kill(pid, signal.SIGTERM)
            signaled = True
        except ProcessLookupError:
            continue
    return signaled


def restart_serve_background(
    project_dir: Path | None = None,
    *,
    dev: bool = True,
) -> ServeStatus:
    """Stop then start shared HTTP serve so package bumps pick up a new process."""
    root = resolve_project_dir(project_dir)
    stop_serve_background(root)
    _wait_until_stopped(root, timeout_s=3.0)
    return start_serve_background(root, dev=dev, force=True)
