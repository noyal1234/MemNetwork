"""HTTP MCP bind guards, bearer token, and Starlette auth middleware."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from brainkm.services.mcp_http_auth import (
    RemoteBindDeniedError,
    assert_bind_allowed,
    ensure_mcp_http_token,
    extract_bearer_token,
    is_loopback_host,
    load_mcp_http_token,
    mcp_http_token_path,
    token_matches,
)
from brainkm.services.mcp_transport import build_mcp_config, mcp_entry_has_bearer_header


def test_is_loopback_host() -> None:
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("localhost")
    assert is_loopback_host("::1")
    assert not is_loopback_host("0.0.0.0")
    assert not is_loopback_host("192.168.1.10")


def test_assert_bind_allowed_refuses_remote() -> None:
    with pytest.raises(RemoteBindDeniedError):
        assert_bind_allowed("0.0.0.0", allow_remote=False)
    assert_bind_allowed("0.0.0.0", allow_remote=True)
    assert_bind_allowed("127.0.0.1", allow_remote=False)


def test_ensure_mcp_http_token_persists(tmp_path: Path) -> None:
    token = ensure_mcp_http_token(tmp_path)
    assert token
    assert mcp_http_token_path(tmp_path).is_file()
    assert load_mcp_http_token(tmp_path) == token
    assert ensure_mcp_http_token(tmp_path) == token


def test_mcp_http_token_file_is_owner_only(tmp_path: Path) -> None:
    ensure_mcp_http_token(tmp_path)
    path = mcp_http_token_path(tmp_path)
    assert (path.stat().st_mode & 0o777) == 0o600

    # Loading re-restricts tokens created by older versions with loose perms.
    path.chmod(0o644)
    assert load_mcp_http_token(tmp_path)
    assert (path.stat().st_mode & 0o777) == 0o600


def test_token_matches_constant_time() -> None:
    assert token_matches("abc", "abc")
    assert not token_matches("abc", "abd")
    assert not token_matches(None, "abc")
    assert extract_bearer_token("Bearer secret") == "secret"
    assert extract_bearer_token("Basic x") is None


def test_build_mcp_config_http_includes_headers() -> None:
    payload = build_mcp_config(
        transport="http",
        port=8765,
        http_token="test-token-value",
    )
    server = payload["mcpServers"]["brainkm"]
    assert server["url"] == "http://127.0.0.1:8765/mcp/"
    assert server["headers"]["Authorization"] == "Bearer test-token-value"
    assert mcp_entry_has_bearer_header(server)


def test_http_mcp_middleware_and_health(tmp_path: Path) -> None:
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Mount, Route

    from brainkm import __version__
    from brainkm.db.migrate import migrate
    from brainkm.server import _register_sampling_callback, create_server
    from brainkm.services.config_loader import load_brain_config
    from brainkm.services.graphify_sync import (
        start_graph_sync_scheduler,
        stop_graph_sync_scheduler,
    )
    from brainkm.tools.dispatch import BrainRuntime

    migrate(project_dir=tmp_path, run_integrity_check=False)
    token = ensure_mcp_http_token(tmp_path)
    brain_config = load_brain_config(tmp_path)
    runtime = BrainRuntime(project_dir=tmp_path)
    server = create_server(runtime)
    _register_sampling_callback(server)
    start_graph_sync_scheduler(tmp_path, brain_config)
    manager = StreamableHTTPSessionManager(app=server, json_response=True, stateless=True)

    async def lifespan(app):  # noqa: ANN001, ARG001
        async with manager.run():
            yield

    async def health(request: Request) -> JSONResponse:
        payload: dict[str, object] = {"ok": True, "version": __version__}
        provided = extract_bearer_token(request.headers.get("Authorization"))
        if token_matches(provided, token):
            payload["project_dir"] = str(tmp_path.resolve())
        return JSONResponse(payload)

    class _McpBearerMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):  # noqa: ANN001
            path = request.url.path
            if path == "/mcp" or path.startswith("/mcp/"):
                provided = extract_bearer_token(request.headers.get("Authorization"))
                if not token_matches(provided, token):
                    return Response("Unauthorized", status_code=401, media_type="text/plain")
            return await call_next(request)

    app = Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Mount("/mcp", app=manager.handle_request),
        ],
        lifespan=lifespan,
    )
    app.add_middleware(_McpBearerMiddleware)

    try:
        with TestClient(app) as client:
            anon = client.get("/health")
            assert anon.status_code == 200
            body = anon.json()
            assert body["ok"] is True
            assert "project_dir" not in body

            authed = client.get(
                "/health",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert authed.status_code == 200
            assert "project_dir" in authed.json()

            denied = client.post("/mcp", json={})
            assert denied.status_code == 401
    finally:
        stop_graph_sync_scheduler()
