"""MCP wiring doctor — health, client configs, dual-writer warnings."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from brainkm import __version__
from brainkm.services.config_loader import load_brain_config
from brainkm.services.connect import hooks_path_for_client, mcp_config_path_for_client
from brainkm.services.install import BRAINKM_MCP_SERVER_KEY, resolve_project_dir
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


def _inspect_mcp_entry(entry: object) -> tuple[str | None, str | None]:
    if not isinstance(entry, dict):
        return None, None
    if entry.get("url"):
        return "http", str(entry["url"])
    if entry.get("command"):
        return "stdio", None
    return None, None


def _client_status(project_dir: Path, client: str) -> ClientWireStatus:
    mcp_path = mcp_config_path_for_client(project_dir, client)
    hooks_path = hooks_path_for_client(project_dir, client)
    status = ClientWireStatus(
        client=client,
        mcp_path=mcp_path,
        present=mcp_path.is_file(),
        transport=None,
        hooks_present=bool(hooks_path and hooks_path.is_file()),
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

    return McpDoctorReport(
        project_dir=root,
        health_ok=health_ok,
        health_url=mcp_health_url(host=resolved_host, port=resolved_port),
        health_detail=health_detail,
        config_transport=cfg.mcp.transport,
        auto_observe=cfg.capture.auto_observe,
        clients=clients,
        dual_writer_warning=dual,
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
    if report.dual_writer_warning:
        lines.append(f"WARNING: {report.dual_writer_warning}")
    if report.config_transport == "http" and not report.health_ok:
        lines.append("HINT: start the shared server with `brainkm serve --project-dir .`")
    return "\n".join(lines)
