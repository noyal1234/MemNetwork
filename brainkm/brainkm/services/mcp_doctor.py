"""MCP wiring doctor — health, client configs, dual-writer warnings, Claude hooks."""

from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from brainkm import __version__
from brainkm.services.config_loader import load_brain_config
from brainkm.services.connect import hooks_path_for_client, mcp_config_path_for_client
from brainkm.services.install import BRAINKM_MCP_SERVER_KEY, resolve_hook_command, resolve_project_dir
from brainkm.services.mcp_transport import mcp_health_url


@dataclass
class ClientWireStatus:
    client: str
    mcp_path: Path
    present: bool
    transport: str | None  # "http" | "stdio" | None
    url: str | None = None
    hooks_present: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class McpDoctorReport:
    project_dir: Path
    health_ok: bool
    health_url: str
    health_detail: str
    config_transport: str
    auto_observe: bool
    clients: list[ClientWireStatus]
    dual_writer_warning: str | None = None
    version: str = __version__
    claude_notes: list[str] = field(default_factory=list)


def _inspect_mcp_entry(entry: object) -> tuple[str | None, str | None]:
    if not isinstance(entry, dict):
        return None, None
    if entry.get("url"):
        return "http", str(entry["url"])
    if entry.get("command"):
        return "stdio", None
    return None, None


def _claude_settings_has_brainkm_hooks(settings_path: Path) -> bool:
    if not settings_path.is_file():
        return False
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    hooks = data.get("hooks") if isinstance(data, dict) else None
    if not isinstance(hooks, dict):
        return False
    for groups in hooks.values():
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            handlers = group.get("hooks")
            if not isinstance(handlers, list):
                continue
            for handler in handlers:
                if isinstance(handler, dict) and "brainkm" in str(handler.get("command", "")):
                    return True
    return False


def _first_brainkm_hook_command(settings_path: Path) -> str | None:
    if not settings_path.is_file():
        return None
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    hooks = data.get("hooks") if isinstance(data, dict) else None
    if not isinstance(hooks, dict):
        return None
    for groups in hooks.values():
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            handlers = group.get("hooks")
            if not isinstance(handlers, list):
                continue
            for handler in handlers:
                if not isinstance(handler, dict):
                    continue
                command = str(handler.get("command", ""))
                if "brainkm" in command:
                    return command
    return None


def _probe_claude_session_start_stdout(project_dir: Path) -> list[str]:
    """Dry-run session-start --client claude; expect hookSpecificOutput or empty success."""
    notes: list[str] = []
    brainkm_bin = resolve_hook_command(dev=False)
    cmd = [
        brainkm_bin,
        "session-start",
        "--stdin",
        "--client",
        "claude",
        "--project-dir",
        str(project_dir),
    ]
    if brainkm_bin == "brainkm" and not shutil.which("brainkm"):
        notes.append("brainkm not on PATH — cannot dry-run SessionStart stdout")
        return notes
    try:
        proc = subprocess.run(
            cmd,
            input='{"session_id":"doctor-probe"}\n',
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            cwd=str(project_dir),
        )
    except FileNotFoundError:
        notes.append(f"hook binary missing: {brainkm_bin}")
        return notes
    except subprocess.TimeoutExpired:
        notes.append("SessionStart dry-run timed out")
        return notes

    if proc.returncode != 0:
        notes.append(f"SessionStart dry-run exited {proc.returncode} (Claude hooks must be fail-soft)")
        return notes

    out = (proc.stdout or "").strip()
    if not out:
        notes.append("SessionStart dry-run: empty stdout (ok if pack skipped)")
        return notes
    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        notes.append(
            "SessionStart dry-run: stdout is not JSON — Claude requires "
            "hookSpecificOutput envelope (Cursor-shaped stdout will be ignored)"
        )
        return notes
    specific = payload.get("hookSpecificOutput") if isinstance(payload, dict) else None
    if not isinstance(specific, dict):
        notes.append("SessionStart dry-run: missing hookSpecificOutput")
        return notes
    if specific.get("hookEventName") != "SessionStart":
        notes.append(
            f"SessionStart dry-run: hookEventName={specific.get('hookEventName')!r} "
            "(expected 'SessionStart')"
        )
        return notes
    if "additionalContext" not in specific and "additional_context" in payload:
        notes.append("SessionStart dry-run: Cursor-shaped additional_context detected — wrong client")
        return notes
    notes.append("SessionStart dry-run: hookSpecificOutput ok")
    return notes


def claude_hooks_wired(project_dir: Path) -> bool:
    """True when project ``.claude/settings.json`` contains brainkm hook commands."""
    return _claude_settings_has_brainkm_hooks(
        resolve_project_dir(project_dir) / ".claude" / "settings.json"
    )


def inspect_claude_wiring(project_dir: Path) -> list[str]:
    """Extra Claude silent-memory checks for doctor."""
    notes: list[str] = []
    root = resolve_project_dir(project_dir)
    settings = root / ".claude" / "settings.json"
    legacy = root / ".claude" / "hooks.json"
    mcp = root / ".mcp.json"

    if not mcp.is_file():
        notes.append("Claude .mcp.json missing — run `brainkm install --client claude` or connect")
    else:
        try:
            data = json.loads(mcp.read_text(encoding="utf-8"))
            servers = data.get("mcpServers") if isinstance(data, dict) else None
            if not isinstance(servers, dict) or BRAINKM_MCP_SERVER_KEY not in servers:
                notes.append("Claude .mcp.json has no brainkm server entry")
        except json.JSONDecodeError:
            notes.append("Claude .mcp.json is not valid JSON")

    if legacy.is_file() and not _claude_settings_has_brainkm_hooks(settings):
        notes.append(
            "Legacy .claude/hooks.json present without brainkm hooks in "
            ".claude/settings.json — Claude Code will not load hooks.json"
        )
    elif legacy.is_file():
        notes.append(
            "Legacy .claude/hooks.json still present — safe to delete after verifying settings hooks"
        )

    if not _claude_settings_has_brainkm_hooks(settings):
        notes.append(
            "No brainkm hooks in .claude/settings.json — run "
            "`brainkm install --client claude` or `brainkm connect claude --hooks`"
        )
    else:
        command = _first_brainkm_hook_command(settings)
        if command:
            binary = command.split()[0]
            if binary not in ("brainkm",) and not Path(binary).is_file() and not shutil.which(binary):
                notes.append(f"Hook binary not found: {binary}")
            if "--client claude" not in command:
                notes.append("Claude hooks missing `--client claude` (stdout may be Cursor-shaped)")
            if "post-compact" in command and "--stdin" not in command:
                notes.append("PostCompact hook missing --stdin")

    notes.extend(_probe_claude_session_start_stdout(root))
    return notes


def _client_status(project_dir: Path, client: str) -> ClientWireStatus:
    mcp_path = mcp_config_path_for_client(project_dir, client)
    hooks_path = hooks_path_for_client(project_dir, client)
    if client == "claude":
        hooks_present = _claude_settings_has_brainkm_hooks(
            project_dir / ".claude" / "settings.json"
        )
    else:
        hooks_present = bool(hooks_path and hooks_path.is_file())
    status = ClientWireStatus(
        client=client,
        mcp_path=mcp_path,
        present=mcp_path.is_file(),
        transport=None,
        hooks_present=hooks_present,
    )
    if not status.present:
        status.notes.append("mcp config missing — run brainkm connect")
        return status
    try:
        data = json.loads(mcp_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        status.notes.append("mcp config is not valid JSON")
        return status
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    entry = servers.get(BRAINKM_MCP_SERVER_KEY) if isinstance(servers, dict) else None
    transport, url = _inspect_mcp_entry(entry)
    status.transport = transport
    status.url = url
    if transport is None:
        status.notes.append("brainkm server entry missing or incomplete")
    return status


def probe_health(*, host: str, port: int, timeout: float = 2.0) -> tuple[bool, str]:
    url = mcp_health_url(host=host, port=port)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            body = resp.read().decode("utf-8", errors="replace")
            if resp.status == 200:
                return True, body[:500]
            return False, f"HTTP {resp.status}: {body[:200]}"
    except urllib.error.URLError as exc:
        return False, f"unreachable: {exc}"
    except Exception as exc:  # pragma: no cover
        return False, f"error: {exc}"


def build_mcp_doctor_report(
    project_dir: Path | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
) -> McpDoctorReport:
    root = resolve_project_dir(project_dir)
    cfg = load_brain_config(root)
    resolved_host = host or cfg.mcp.http_host
    resolved_port = port or cfg.mcp.http_port
    health_ok, health_detail = probe_health(host=resolved_host, port=resolved_port)
    clients = [
        _client_status(root, name)
        for name in ("cursor", "claude", "codex", "generic")
    ]

    dual: str | None = None
    if cfg.mcp.transport == "http":
        stdio_clients = [c.client for c in clients if c.transport == "stdio"]
        if stdio_clients:
            dual = (
                "Dual writer risk: config.mcp.transport=http but these clients still "
                f"use stdio spawn: {', '.join(stdio_clients)}. "
                "Run `brainkm connect <client> --http` or remove stale command/args."
            )

    claude_notes: list[str] = []
    claude_status = next((c for c in clients if c.client == "claude"), None)
    if claude_status and (claude_status.present or (root / ".claude").is_dir()):
        claude_notes = inspect_claude_wiring(root)

    return McpDoctorReport(
        project_dir=root,
        health_ok=health_ok,
        health_url=mcp_health_url(host=resolved_host, port=resolved_port),
        health_detail=health_detail,
        config_transport=cfg.mcp.transport,
        auto_observe=cfg.capture.auto_observe,
        clients=clients,
        dual_writer_warning=dual,
        claude_notes=claude_notes,
    )


def format_mcp_doctor_report(report: McpDoctorReport) -> str:
    lines = [
        f"brainkm doctor (v{report.version})",
        f"project: {report.project_dir}",
        f"config.mcp.transport: {report.config_transport}",
        f"capture.auto_observe: {report.auto_observe}",
        f"health ({report.health_url}): {'ok' if report.health_ok else 'FAIL'}",
        f"  {report.health_detail}",
        "clients:",
    ]
    for client in report.clients:
        flag = "yes" if client.present else "no"
        lines.append(
            f"  {client.client}: mcp={flag} transport={client.transport or '-'} "
            f"hooks={'yes' if client.hooks_present else 'no'}"
        )
        for note in client.notes:
            lines.append(f"    note: {note}")
    if report.claude_notes:
        lines.append("claude silent-memory:")
        for note in report.claude_notes:
            lines.append(f"  - {note}")
    if report.dual_writer_warning:
        lines.append(f"WARNING: {report.dual_writer_warning}")
    if report.config_transport == "http" and not report.health_ok:
        lines.append("HINT: start the shared server with `brainkm serve --project-dir .`")
    return "\n".join(lines)
