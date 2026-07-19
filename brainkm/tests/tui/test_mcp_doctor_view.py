"""Unit tests for Dashboard MCP doctor StatusPanel mapping."""

from __future__ import annotations

from pathlib import Path

from brainkm.services.mcp_doctor import ClientWireStatus, McpDoctorReport
from brainkm.tui.mcp_doctor_view import mcp_doctor_panel_items


def _report(**overrides: object) -> McpDoctorReport:
    base = McpDoctorReport(
        project_dir=Path("/tmp/proj"),
        health_ok=True,
        health_url="http://127.0.0.1:8765/health",
        health_detail='{"ok":true}',
        config_transport="http",
        auto_observe=True,
        clients=[
            ClientWireStatus(
                client="cursor",
                mcp_path=Path("/tmp/proj/.cursor/mcp.json"),
                present=True,
                transport="http",
                url="http://127.0.0.1:8765/mcp",
                hooks_present=True,
                has_bearer=True,
            ),
            ClientWireStatus(
                client="antigravity",
                mcp_path=Path("/tmp/proj/.agents/mcp_config.json"),
                present=True,
                transport="http",
                url="http://127.0.0.1:8765/mcp",
                hooks_present=True,
                has_bearer=False,
                notes=["HTTP MCP entry missing Authorization Bearer header"],
            ),
        ],
        missing_auth_warning=(
            "HTTP MCP clients missing Authorization Bearer header: antigravity"
        ),
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def test_panel_items_flag_missing_bearer() -> None:
    items = mcp_doctor_panel_items(_report())
    by_label = {label: (value, state) for label, value, state in items}
    assert by_label["Overall"][1] == "error"
    assert by_label["Transport"] == ("http", "ok")
    assert by_label["Health"][1] == "ok"
    assert by_label["Observe"] == ("on", "ok")
    assert by_label["cursor"][1] == "ok"
    assert by_label["agy"][1] == "warning"
    assert "Auth" in by_label
    assert by_label["Auth"][1] == "error"


def test_panel_items_stdio_healthy_without_http_health() -> None:
    items = mcp_doctor_panel_items(
        _report(
            config_transport="stdio",
            health_ok=False,
            auto_observe=False,
            missing_auth_warning=None,
            clients=[
                ClientWireStatus(
                    client="cursor",
                    mcp_path=Path("/tmp/.cursor/mcp.json"),
                    present=True,
                    transport="stdio",
                    hooks_present=True,
                    has_bearer=False,
                ),
            ],
        )
    )
    by_label = {label: (value, state) for label, value, state in items}
    assert by_label["Overall"] == ("HEALTHY", "ok")
    assert by_label["Transport"] == ("stdio", "muted")
    assert by_label["Health"][1] == "muted"
