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
    install_client_guidance_assets,
    merge_hooks_json,
    resolve_hook_command,
    resolve_project_dir,
    write_antigravity_hooks,
    write_claude_settings_hooks,
    write_codex_hooks,
)
from brainkm.services.mcp_http_auth import ensure_mcp_http_token, restrict_secret_file
from brainkm.services.mcp_transport import (
    BRAINKM_MCP_SERVER_KEY,
    DEFAULT_HTTP_PORT,
    build_mcp_config,
    mcp_http_url,
    normalize_mcp_entry_transport_fields,
    write_codex_mcp_config,
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
        entry = servers.get(BRAINKM_MCP_SERVER_KEY)
        if isinstance(entry, dict):
            servers[BRAINKM_MCP_SERVER_KEY] = normalize_mcp_entry_transport_fields(entry)
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
        return project_dir / ".codex" / "config.toml"
    if kind == "antigravity":
        return project_dir / ".agents" / "mcp_config.json"
    return project_dir / ".brain" / "mcp.http.example.json"


def hooks_path_for_client(project_dir: Path, client: str) -> Path | None:
    kind = str(client).lower()
    if kind == "cursor":
        return project_dir / ".cursor" / "hooks.json"
    if kind == "claude":
        return project_dir / ".claude" / "settings.json"
    if kind == "codex":
        return project_dir / ".codex" / "hooks.json"
    if kind == "antigravity":
        return project_dir / ".agents" / "hooks.json"
    return None


FIRST_CLASS_CLIENTS: tuple[str, ...] = ("cursor", "claude", "antigravity", "codex")


def detect_wired_clients(project_dir: Path | None = None) -> list[str]:
    """Clients that already have MCP or hooks scaffolding on disk.

    Used by the configure wizard to pre-check apps on re-runs instead of
    always defaulting to Cursor-only.
    """
    from brainkm.services.install import resolve_project_dir

    root = resolve_project_dir(project_dir)
    found: list[str] = []
    for name in FIRST_CLASS_CLIENTS:
        mcp = mcp_config_path_for_client(root, name)
        hooks = hooks_path_for_client(root, name)
        if mcp.is_file() or (hooks is not None and hooks.is_file()):
            found.append(name)
    return found


def antigravity_global_mcp_paths() -> list[Path]:
    """Known global / legacy Antigravity MCP config locations (doctor + optional mirror)."""
    home = Path.home()
    paths = [
        home / ".gemini" / "config" / "mcp_config.json",
        home / ".gemini" / "antigravity-cli" / "mcp_config.json",
    ]
    # macOS IDE Application Support variant
    app_support = (
        home / "Library" / "Application Support" / "Antigravity" / "User" / "mcp_config.json"
    )
    paths.append(app_support)
    return paths


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
    mirror_global: bool = False,
) -> ConnectResult:
    """Wire one client to stdio or shared HTTP MCP for this project."""
    root = resolve_project_dir(project_dir)
    kind = str(client).lower()
    adapter = get_client_adapter(kind)

    result = ConnectResult(
        project_dir=root,
        client=kind,
        transport=transport,
        mcp_url=mcp_http_url(host=host, port=port) if transport == "http" else None,
    )

    http_token = ensure_mcp_http_token(root) if transport == "http" else None
    mcp_path = mcp_config_path_for_client(root, kind)
    if kind == "codex":
        write_codex_mcp_config(
            mcp_path,
            dev=dev,
            transport=transport,
            host=host,
            port=port,
            http_token=http_token,
        )
    else:
        payload = build_mcp_config(
            dev=dev,
            transport=transport,
            host=host,
            port=port,
            client=kind,
            http_token=http_token,
        )
        _merge_mcp_file(mcp_path, payload)
    if http_token:
        restrict_secret_file(mcp_path)
    result.files_written.append(mcp_path)

    if kind == "antigravity" and mirror_global:
        payload = build_mcp_config(
            dev=dev,
            transport=transport,
            host=host,
            port=port,
            client=kind,
            http_token=http_token,
        )
        for gpath in antigravity_global_mcp_paths()[:1]:  # shared ~/.gemini/config only
            try:
                _merge_mcp_file(gpath, payload)
                if http_token:
                    restrict_secret_file(gpath)
                result.files_written.append(gpath)
            except OSError as exc:
                result.warnings.append(f"mirror-global failed for {gpath}: {exc}")

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
            elif kind == "antigravity":
                write_antigravity_hooks(hooks_path, brainkm_bin, project_dir=root)
                result.files_written.append(hooks_path)
            elif kind == "codex":
                write_codex_hooks(hooks_path, brainkm_bin)
                result.files_written.append(hooks_path)
                result.warnings.append(
                    "Codex: trust the project `.codex/` layer, then open `/hooks` "
                    "and trust brainkm commands."
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

    # Rules / skills / AGENTS|CLAUDE snippet — same assets as primary install.
    # Multi-app wizard uses connect for secondary clients; without this they
    # only got MCP + hooks and missed routing guidance.
    if kind in ("cursor", "claude", "antigravity", "codex"):
        guidance = install_client_guidance_assets(root, kind, force=False)
        result.files_written.extend(guidance.files_written)

    if update_config:
        cfg = load_brain_config(root)
        data = cfg.model_dump()
        data["mcp"] = {
            "transport": transport,
            "http_host": host,
            "http_port": port,
            "allow_remote": bool(getattr(cfg.mcp, "allow_remote", False)),
        }
        if transport == "http" or kind in ("claude", "antigravity", "codex"):
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
