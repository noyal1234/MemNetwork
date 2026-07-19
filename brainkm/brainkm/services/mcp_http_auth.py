"""HTTP MCP bind guards and bearer-token helpers."""

from __future__ import annotations

import hmac
import ipaddress
import os
import secrets
from pathlib import Path

from brainkm.db.paths import brain_dir
from brainkm.logging_config import get_logger

logger = get_logger("services.mcp_http_auth")

TOKEN_FILENAME = "mcp_http_token"
LOOPBACK_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1", "0:0:0:0:0:0:0:1"})


class RemoteBindDeniedError(ValueError):
    """Raised when HTTP MCP would bind outside loopback without allow_remote."""


def mcp_http_token_path(project_dir: Path | None = None) -> Path:
    return brain_dir(project_dir) / TOKEN_FILENAME


def is_loopback_host(host: str) -> bool:
    """True when *host* is a loopback name or IP."""
    normalized = (host or "").strip().lower()
    if not normalized:
        return False
    if normalized in LOOPBACK_HOSTNAMES:
        return True
    # Strip IPv6 brackets: [::1]
    if normalized.startswith("[") and normalized.endswith("]"):
        normalized = normalized[1:-1]
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def assert_bind_allowed(host: str, *, allow_remote: bool) -> None:
    """Refuse non-loopback binds unless *allow_remote* is set."""
    if allow_remote or is_loopback_host(host):
        return
    raise RemoteBindDeniedError(
        f"Refusing to bind MCP HTTP on non-loopback host {host!r}. "
        "Use 127.0.0.1 (default) or pass --allow-remote / set mcp.allow_remote=true."
    )


def restrict_secret_file(path: Path) -> None:
    """Best-effort owner-only permissions on a file holding a secret."""
    try:
        path.chmod(0o600)
    except OSError:
        pass


def load_mcp_http_token(project_dir: Path | None = None) -> str | None:
    path = mcp_http_token_path(project_dir)
    if not path.is_file():
        return None
    # Re-assert owner-only perms on tokens created by older versions.
    restrict_secret_file(path)
    token = path.read_text(encoding="utf-8").strip()
    return token or None


def ensure_mcp_http_token(project_dir: Path | None = None) -> str:
    """Load or create a per-project HTTP MCP bearer token under ``.brain/``."""
    existing = load_mcp_http_token(project_dir)
    if existing:
        return existing
    path = mcp_http_token_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    # O_CREAT with 0600 avoids the umask window a write-then-chmod would leave.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token + "\n")
    restrict_secret_file(path)
    logger.info(
        "Generated MCP HTTP bearer token at %s — reconnect clients "
        "(brainkm connect <client> --http)",
        path,
    )
    return token


def bearer_authorization_header(token: str) -> str:
    return f"Bearer {token}"


def extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def token_matches(provided: str | None, expected: str) -> bool:
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))
