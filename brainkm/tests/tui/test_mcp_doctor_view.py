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
                url="http://127.0.0.1:8765/mcp/",
                hooks_present=True,
                has_bearer=True,
            ),
            ClientWireStatus(
                client="antigravity",
                mcp_path=Path("/tmp/proj/.agents/mcp_config.json"),
                present=True,
                transport="http",
                url="http://127.0.0.1:8765/mcp/",
                hooks_present=True,
                has_bearer=False,
                notes=["HTTP MCP entry missing Authorization Bearer header"],
            ),
        ],
        missing_auth_warning=("HTTP MCP clients missing Authorization Bearer header: antigravity"),
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


def test_panel_always_shows_absent_codex_like_claude() -> None:
    items = mcp_doctor_panel_items(
        _report(
            missing_auth_warning=None,
            clients=[
                ClientWireStatus(
                    client="cursor",
                    mcp_path=Path("/tmp/proj/.cursor/mcp.json"),
                    present=True,
                    transport="http",
                    hooks_present=True,
                    has_bearer=True,
                ),
                ClientWireStatus(
                    client="claude",
                    mcp_path=Path("/tmp/proj/.mcp.json"),
                    present=False,
                    transport=None,
                ),
                ClientWireStatus(
                    client="codex",
                    mcp_path=Path("/tmp/proj/.codex/config.toml"),
                    present=False,
                    transport=None,
                ),
                ClientWireStatus(
                    client="generic",
                    mcp_path=Path("/tmp/proj/.mcp.json"),
                    present=False,
                    transport=None,
                ),
            ],
            client_notes=[],
        )
    )
    by_label = {label: (value, state) for label, value, state in items}
    assert by_label["claude"] == ("missing", "muted")
    assert by_label["codex"] == ("missing", "muted")
    assert "generic" not in by_label


def test_panel_ok_dry_run_notes_are_probe_not_warning() -> None:
    items = mcp_doctor_panel_items(
        _report(
            missing_auth_warning=None,
            clients=[
                ClientWireStatus(
                    client="antigravity",
                    mcp_path=Path("/tmp/proj/.agents/mcp_config.json"),
                    present=True,
                    transport="http",
                    hooks_present=True,
                    has_bearer=True,
                ),
            ],
            client_notes=[
                "Antigravity PreInvocation dry-run: injectSteps envelope ok",
            ],
        )
    )
    by_label = {label: (value, state) for label, value, state in items}
    assert "Notes" not in by_label
    assert by_label["Tip"][1] == "muted"
    assert "injectSteps" in by_label["Tip"][0]


def test_panel_warning_notes_preferred_over_ok_probes() -> None:
    items = mcp_doctor_panel_items(
        _report(
            missing_auth_warning=None,
            clients=[],
            client_notes=[
                "Antigravity PreInvocation dry-run: injectSteps envelope ok",
                "Codex hooks missing or lack `--client codex`",
            ],
        )
    )
    by_label = {label: (value, state) for label, value, state in items}
    assert "Tip" in by_label or any(
        label == "Tip" for label, _, state in items if state == "muted"
    )
    assert by_label["Notes"][1] == "warning"
    assert "Codex hooks" in by_label["Notes"][0]


def test_panel_notes_wrap_full_codex_trust_message() -> None:
    note = (
        "Reminder (Codex UI): if SessionStart/Stop stay quiet, trust the project "
        "`.codex/` layer and `/hooks` — files alone cannot prove Codex trust"
    )
    items = mcp_doctor_panel_items(
        _report(
            missing_auth_warning=None,
            clients=[],
            client_notes=[note],
        )
    )
    tip_rows = [(label, value, state) for label, value, state in items if state == "muted"]
    assert tip_rows
    assert tip_rows[0][0] == "Tip"
    joined = " ".join(value for _, value, _ in tip_rows)
    assert "Reminder (Codex UI)" in joined
    assert "cannot prove Codex trust" in joined
    assert "…" not in joined
    # Continuations use empty label (indent), not a truncated single cell.
    if len(tip_rows) > 1:
        assert all(label == "" for label, _, _ in tip_rows[1:])
    # No warning Notes for the trust reminder alone.
    assert not any(state == "warning" for _, _, state in items)


def test_panel_multiple_tips_use_tip_labels_not_note() -> None:
    items = mcp_doctor_panel_items(
        _report(
            missing_auth_warning=None,
            clients=[],
            client_notes=[
                "Antigravity PreInvocation dry-run: injectSteps envelope ok",
                "Reminder (Codex UI): if SessionStart/Stop stay quiet, trust the project",
            ],
        )
    )
    tip_heads = [label for label, _, state in items if state == "muted" and label]
    assert tip_heads[0] == "Tip 1"
    assert tip_heads[1] == "Tip 2"
    assert "Note 2" not in tip_heads
    assert not any(state == "warning" for _, _, state in items)

    items = mcp_doctor_panel_items(
        _report(
            missing_auth_warning=None,
            clients=[],
            client_notes=[
                "First warning about hooks trust for Codex.",
                "Second warning about missing Authorization header.",
            ],
        )
    )
    labels = [label for label, _, state in items if state == "warning"]
    assert "Notes" in labels
    assert "Note 2" in labels


def test_panel_health_fail_is_wrapped_not_midword_trunc() -> None:
    items = mcp_doctor_panel_items(
        _report(
            health_ok=False,
            health_detail="unreachable: <urlopen error [Errno 61] Connection refused>",
            missing_auth_warning=None,
            client_notes=[],
            clients=[],
        )
    )
    values: list[str] = []
    in_health = False
    for label, value, state in items:
        if label == "Health":
            in_health = True
            values.append(value)
            continue
        if in_health and label == "":
            values.append(value)
            continue
        if in_health and label:
            break
    joined = " ".join(values)
    assert "connection refused" in joined.lower() or "serve" in joined.lower()
    assert "urlopen" not in joined.lower()
    assert "Connectio…" not in joined
