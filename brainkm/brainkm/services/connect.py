"""Connect agent clients to a shared brainkm MCP (stdio or HTTP)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from brainkm.logging_config import get_logger
from brainkm.models.brain_config import BrainConfig
from brainkm.services.client_adapters import get_client_adapter
from brainkm.services.config_loader import load_brain_config, save_brain_config
from brainkm.services.install import (
    build_hooks_config,
    merge_hooks_json,
    resolve_hook_command,
    resolve_project_dir,
    write_claude_settings_hooks,
)
from brainkm.services.mcp_transport import (
    BRAINKM_MCP_SERVER_KEY,
    DEFAULT_HTTP_PORT,
    build_mcp_config,
    mcp_http_url,
)

logger = get_logger("services.connect")


@dataclass
class ConnectResult:
    project_dir: Path
    client: str
    transport: str
    files_written: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    mcp_url: str | None = None


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _merge_mcp_file(path: Path, payload: dict[str, object]) -> None:
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        servers = existing.get("mcpServers")
        if not isinstance(servers, dict):
            servers = {}
        incoming = payload.get("mcpServers")
        if isinstance(incoming, dict):
            servers = {**servers, **incoming}
        existing["mcpServers"] = servers
        # Drop stale command/args when switching to URL (and vice versa).
        entry = servers.get(BRAINKM_MCP_SERVER_KEY)
        if isinstance(entry, dict):
            if "url" in entry:
                entry.pop("command", None)
                entry.pop("args", None)
            else:
                entry.pop("url", None)
            servers[BRAINKM_MCP_SERVER_KEY] = entry
        _write_json(path, existing)
    else:
        _write_json(path, payload)


def mcp_config_path_for_client(project_dir: Path, client: str) -> Path:
    kind = str(client).lower()
    if kind == "cursor":
        return project_dir / ".cursor" / "mcp.json"
    if kind == "claude":
        return project_dir / ".mcp.json"
    if kind == "codex":
        return project_dir / ".codex" / "mcp.json"
    return project_dir / ".brain" / "mcp.http.example.json"


def hooks_path_for_client(project_dir: Path, client: str) -> Path | None:
    kind = str(client).lower()
    if kind == "cursor":
        return project_dir / ".cursor" / "hooks.json"
    if kind == "claude":
        return project_dir / ".claude" / "settings.json"
    if kind == "codex":
        return project_dir / ".codex" / "hooks.json"
    return None


def run_connect(
    client: str,
    project_dir: Path | None = None,
    *,
    transport: str = "http",
    hooks: bool = True,
    host: str = "127.0.0.1",
    port: int = DEFAULT_HTTP_PORT,
    dev: bool = False,
    update_config: bool = True,
) -> ConnectResult:
    """Wire one client to stdio or shared HTTP MCP for this project."""
    root = resolve_project_dir(project_dir)
    kind = str(client).lower()
    try:
        adapter = get_client_adapter(kind)
    except ValueError:
        # Allow codex before adapter raises — get_client_adapter will include codex.
        raise

    result = ConnectResult(
        project_dir=root,
        client=kind,
        transport=transport,
        mcp_url=mcp_http_url(host=host, port=port) if transport == "http" else None,
    )

    payload = build_mcp_config(
        dev=dev,
        transport=transport,
        host=host,
        port=port,
    )
    mcp_path = mcp_config_path_for_client(root, kind)
    _merge_mcp_file(mcp_path, payload)
    result.files_written.append(mcp_path)

    if kind == "generic":
        result.warnings.append(
            "generic client: wrote example MCP URL block only; paste into your agent config"
        )

    if hooks and adapter.hook_events():
        hooks_path = hooks_path_for_client(root, kind)
        if hooks_path is not None:
            brainkm_bin = resolve_hook_command(dev=dev)
            if kind == "claude":
                write_claude_settings_hooks(hooks_path, brainkm_bin)
                result.files_written.append(hooks_path)
                legacy = root / ".claude" / "hooks.json"
                if legacy.is_file():
                    result.warnings.append(
                        "Legacy .claude/hooks.json found — Claude loads "
                        ".claude/settings.json; remove the legacy file after verifying doctor."
                    )
            elif kind == "cursor":
                hooks_payload = build_hooks_config(brainkm_bin)
                if hooks_path.is_file():
                    existing = json.loads(hooks_path.read_text(encoding="utf-8"))
                    merged = merge_hooks_json(existing, hooks_payload)
                else:
                    merged = merge_hooks_json({}, hooks_payload)
                _write_json(hooks_path, merged)
                result.files_written.append(hooks_path)
            else:
                hooks_payload = build_hooks_config(brainkm_bin)
                if hooks_path.is_file():
                    existing = json.loads(hooks_path.read_text(encoding="utf-8"))
                    from brainkm.services.install import _deep_merge_dict

                    merged = _deep_merge_dict(existing, hooks_payload)
                    _write_json(hooks_path, merged)
                else:
                    _write_json(hooks_path, hooks_payload)
                result.files_written.append(hooks_path)

    if update_config:
        cfg = load_brain_config(root)
        data = cfg.model_dump()
        data["mcp"] = {
            "transport": transport,
            "http_host": host,
            "http_port": port,
        }
        if transport == "http" or kind == "claude":
            capture = data.setdefault("capture", {})
            if isinstance(capture, dict):
                capture["auto_observe"] = True
        save_brain_config(root, BrainConfig.model_validate(data))

    logger.info(
        "connect client=%s transport=%s project_dir=%s",
        kind,
        transport,
        root,
    )
    return result
