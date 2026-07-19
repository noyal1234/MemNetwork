"""Build stdio vs URL MCP client configs for shared localhost brain."""

from __future__ import annotations

from brainkm.models.brain_config import BrainConfig, McpConfig

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
) -> dict[str, object]:
    """Single ``mcpServers.brainkm`` entry — stdio spawn or URL to shared serve."""
    field = http_url_field
    if client is not None:
        field = http_url_field_for_client(client)
    if transport == "http":
        return {
            field: mcp_http_url(host=host, port=port),
        }
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
            )
        }
    }


def build_mcp_config_from_brain(
    config: BrainConfig,
    *,
    dev: bool = False,
    client: str | None = None,
) -> dict[str, object]:
    mcp: McpConfig = config.mcp
    return build_mcp_config(
        dev=dev,
        transport=mcp.transport,
        host=mcp.http_host,
        port=mcp.http_port,
        client=client,
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
            # Keep both only if identical; otherwise prefer serverUrl for AGY merges.
            if str(out.get("url")) == str(out.get("serverUrl")):
                out.pop("url", None)
    else:
        out.pop("url", None)
        out.pop("serverUrl", None)
    return out
