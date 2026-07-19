"""Build stdio vs URL MCP client configs for shared localhost brain."""

from __future__ import annotations

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
    headers = entry.get("headers")
    if not isinstance(headers, dict):
        return False
    auth = headers.get("Authorization") or headers.get("authorization")
    if not isinstance(auth, str):
        return False
    return auth.strip().lower().startswith("bearer ")
