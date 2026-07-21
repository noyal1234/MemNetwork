"""Build stdio vs URL MCP client configs for shared localhost brain."""

from __future__ import annotations

from pathlib import Path

from brainkm.models.brain_config import BrainConfig, McpConfig
from brainkm.services.mcp_http_auth import bearer_authorization_header

BRAINKM_MCP_SERVER_KEY = "brainkm"
DEFAULT_HTTP_PORT = 8765

# Cursor / Claude / Codex use ``url``; Antigravity requires ``serverUrl``.
HTTP_URL_FIELD_BY_CLIENT: dict[str, str] = {
    "cursor": "url",
    "claude": "url",
    "codex": "url",
    "generic": "url",
    "antigravity": "serverUrl",
}


def mcp_http_url(*, host: str = "127.0.0.1", port: int = DEFAULT_HTTP_PORT) -> str:
    return f"http://{host}:{port}/mcp"


def mcp_health_url(*, host: str = "127.0.0.1", port: int = DEFAULT_HTTP_PORT) -> str:
    return f"http://{host}:{port}/health"


def http_url_field_for_client(client: str | None = None) -> str:
    kind = str(client or "cursor").lower()
    return HTTP_URL_FIELD_BY_CLIENT.get(kind, "url")


def build_mcp_server_entry(
    *,
    dev: bool = False,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = DEFAULT_HTTP_PORT,
    project_dir: str = ".",
    http_url_field: str = "url",
    client: str | None = None,
    http_token: str | None = None,
) -> dict[str, object]:
    """Single ``mcpServers.brainkm`` entry — stdio spawn or URL to shared serve."""
    field = http_url_field
    if client is not None:
        field = http_url_field_for_client(client)
    if transport == "http":
        entry: dict[str, object] = {
            field: mcp_http_url(host=host, port=port),
        }
        if http_token:
            entry["headers"] = {
                "Authorization": bearer_authorization_header(http_token),
            }
        return entry
    from brainkm.services.install import resolve_brainkm_command

    command, args = resolve_brainkm_command(dev=dev)
    if "--project-dir" not in args:
        args = [*args, "--project-dir", project_dir]
    return {
        "command": command,
        "args": args,
    }


def build_mcp_config(
    *,
    dev: bool = False,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = DEFAULT_HTTP_PORT,
    project_dir: str = ".",
    http_url_field: str = "url",
    client: str | None = None,
    http_token: str | None = None,
) -> dict[str, object]:
    return {
        "mcpServers": {
            BRAINKM_MCP_SERVER_KEY: build_mcp_server_entry(
                dev=dev,
                transport=transport,
                host=host,
                port=port,
                project_dir=project_dir,
                http_url_field=http_url_field,
                client=client,
                http_token=http_token,
            )
        }
    }


def build_mcp_config_from_brain(
    config: BrainConfig,
    *,
    dev: bool = False,
    client: str | None = None,
    http_token: str | None = None,
) -> dict[str, object]:
    mcp: McpConfig = config.mcp
    return build_mcp_config(
        dev=dev,
        transport=mcp.transport,
        host=mcp.http_host,
        port=mcp.http_port,
        client=client,
        http_token=http_token,
    )


def normalize_mcp_entry_transport_fields(entry: dict[str, object]) -> dict[str, object]:
    """Ensure HTTP entries keep one URL key; drop stale stdio fields when HTTP."""
    out = dict(entry)
    has_http = "url" in out or "serverUrl" in out
    if has_http:
        out.pop("command", None)
        out.pop("args", None)
        # Prefer serverUrl when both present (Antigravity).
        if "serverUrl" in out and "url" in out:
            out.pop("url", None)
    else:
        out.pop("url", None)
        out.pop("serverUrl", None)
        out.pop("headers", None)
    return out


def mcp_entry_has_bearer_header(entry: object) -> bool:
    """True when an MCP server entry includes an Authorization Bearer header."""
    if not isinstance(entry, dict):
        return False
    for key in ("headers", "http_headers"):
        headers = entry.get(key)
        if not isinstance(headers, dict):
            continue
        auth = headers.get("Authorization") or headers.get("authorization")
        if isinstance(auth, str) and auth.strip().lower().startswith("bearer "):
            return True
    return False


def build_codex_mcp_server_table(
    *,
    dev: bool = False,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = DEFAULT_HTTP_PORT,
    project_dir: str = ".",
    http_token: str | None = None,
) -> dict[str, object]:
    """Codex ``[mcp_servers.brainkm]`` table values (stdio or HTTP).

    Codex reads TOML under ``.codex/config.toml`` (not JSON ``mcp.json``).
    HTTP auth uses ``http_headers`` (not Cursor/Claude ``headers``).
    """
    if transport == "http":
        entry: dict[str, object] = {
            "url": mcp_http_url(host=host, port=port),
        }
        if http_token:
            entry["http_headers"] = {
                "Authorization": bearer_authorization_header(http_token),
            }
        return entry
    from brainkm.services.install import resolve_brainkm_command

    command, args = resolve_brainkm_command(dev=dev)
    if "--project-dir" not in args:
        args = [*args, "--project-dir", project_dir]
    return {
        "command": command,
        "args": args,
    }


def normalize_codex_mcp_server_table(entry: dict[str, object]) -> dict[str, object]:
    """Drop stale stdio/HTTP fields so Codex sees one coherent transport."""
    out = dict(entry)
    has_http = "url" in out
    if has_http:
        out.pop("command", None)
        out.pop("args", None)
        # Prefer Codex http_headers; drop Cursor-shaped headers if both exist.
        if "http_headers" in out and "headers" in out:
            out.pop("headers", None)
        elif "headers" in out and "http_headers" not in out:
            headers = out.pop("headers")
            if isinstance(headers, dict):
                out["http_headers"] = headers
    else:
        out.pop("url", None)
        out.pop("http_headers", None)
        out.pop("headers", None)
        out.pop("bearer_token_env_var", None)
    return out


def write_codex_mcp_config(
    config_path: Path,
    *,
    dev: bool = False,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = DEFAULT_HTTP_PORT,
    project_dir: str = ".",
    http_token: str | None = None,
) -> dict[str, object]:
    """Merge ``[mcp_servers.brainkm]`` into project ``.codex/config.toml``."""
    import tomlkit
    from tomlkit.items import Table

    incoming = normalize_codex_mcp_server_table(
        build_codex_mcp_server_table(
            dev=dev,
            transport=transport,
            host=host,
            port=port,
            project_dir=project_dir,
            http_token=http_token,
        )
    )
    if config_path.is_file():
        doc = tomlkit.parse(config_path.read_text(encoding="utf-8"))
    else:
        doc = tomlkit.document()

    mcp_servers = doc.get("mcp_servers")
    if not isinstance(mcp_servers, Table):
        mcp_servers = tomlkit.table(is_super_table=True)
        doc["mcp_servers"] = mcp_servers

    server = mcp_servers.get(BRAINKM_MCP_SERVER_KEY)
    if not isinstance(server, Table):
        server = tomlkit.table()
        mcp_servers[BRAINKM_MCP_SERVER_KEY] = server
    else:
        # Clear stale transport keys before writing the active shape.
        for stale in (
            "command",
            "args",
            "url",
            "http_headers",
            "headers",
            "bearer_token_env_var",
        ):
            if stale in server:
                del server[stale]

    for key, value in incoming.items():
        if isinstance(value, dict):
            nested = tomlkit.inline_table()
            for nested_key, nested_value in value.items():
                nested[nested_key] = nested_value
            server[key] = nested
        elif isinstance(value, list):
            arr = tomlkit.array()
            for item in value:
                arr.append(item)
            server[key] = arr
        else:
            server[key] = value

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return incoming


def read_codex_mcp_server_entry(config_path: Path) -> dict[str, object] | None:
    """Return the ``[mcp_servers.brainkm]`` table as a plain dict, if present."""
    if not config_path.is_file():
        return None
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover
        import tomli as tomllib  # type: ignore[no-redef]

    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    servers = data.get("mcp_servers")
    if not isinstance(servers, dict):
        return None
    entry = servers.get(BRAINKM_MCP_SERVER_KEY)
    if not isinstance(entry, dict):
        return None
    return dict(entry)
