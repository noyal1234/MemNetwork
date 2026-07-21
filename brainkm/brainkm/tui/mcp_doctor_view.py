"""Map McpDoctorReport → StatusPanel (label, value, state) rows for the Dashboard."""

from __future__ import annotations

from brainkm.services.mcp_doctor import ClientWireStatus, McpDoctorReport

_MAX_VALUE = 56


def _trunc(text: str, limit: int = _MAX_VALUE) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


_CLIENT_LABELS = {
    "antigravity": "agy",
    "cursor": "cursor",
    "claude": "claude",
    "codex": "codex",
    "generic": "generic",
}


def _client_row(
    client: ClientWireStatus,
    *,
    config_transport: str,
) -> tuple[str, str, str]:
    label = _CLIENT_LABELS.get(client.client, client.client[:14])
    if not client.present:
        return (label, "missing", "muted")

    parts: list[str] = []
    transport = client.transport or "?"
    parts.append(transport)
    if client.hooks_present:
        parts.append("hooks=yes")
    else:
        parts.append("hooks=no")
    if transport == "http":
        parts.append("auth=yes" if client.has_bearer else "auth=no")

    value = " ".join(parts)
    state = "ok"

    if config_transport == "http" and transport == "stdio":
        state = "error"
    elif transport == "http" and not client.has_bearer:
        state = "warning"
    elif client.notes:
        state = "warning"
    elif not client.hooks_present and client.client in ("cursor", "claude", "antigravity", "codex"):
        state = "warning"

    if client.notes and state != "error":
        # Surface first short note when space allows.
        note = client.notes[0]
        value = _trunc(f"{value} · {note}")

    return (label, _trunc(value), state)


def mcp_doctor_panel_items(
    report: McpDoctorReport,
) -> list[tuple[str, str, str]]:
    """Return StatusPanel items for a doctor report.

    Each item is ``(label, value, state)`` where state is one of
    ``ok`` / ``warning`` / ``error`` / ``muted`` / ``accent``.
    """
    transport = report.config_transport
    dual = bool(report.dual_writer_warning)
    missing_auth = bool(report.missing_auth_warning)
    http_down = transport == "http" and not report.health_ok

    if dual or missing_auth:
        overall_state = "error"
        overall_value = "ISSUES"
    elif http_down:
        overall_state = "warning"
        overall_value = "ISSUES"
    elif transport == "stdio" or report.health_ok:
        overall_state = "ok"
        overall_value = "HEALTHY"
    else:
        overall_state = "warning"
        overall_value = "ISSUES"

    items: list[tuple[str, str, str]] = [
        ("Overall", overall_value, overall_state),
    ]

    if transport == "http":
        t_state = "ok" if report.health_ok else "warning"
    else:
        t_state = "muted"
    items.append(("Transport", transport, t_state))

    if transport == "http":
        health_value = "ok" if report.health_ok else "FAIL"
        if report.health_detail and not report.health_ok:
            health_value = _trunc(f"FAIL · {report.health_detail}")
        elif report.health_ok:
            health_value = "ok"
        items.append(
            ("Health", health_value, "ok" if report.health_ok else "error"),
        )
    else:
        items.append(("Health", "n/a (stdio)", "muted"))

    if transport == "http" and report.auto_observe:
        items.append(("Observe", "on", "ok"))
    else:
        items.append(
            (
                "Observe",
                "on" if report.auto_observe else "off",
                "muted",
            )
        )

    for client in report.clients:
        if not client.present:
            if client.client == "generic":
                continue
            # Show absent Codex only when a `.codex/` tree triggered inspect notes.
            if client.client == "codex" and not any(
                "Codex" in note or "codex" in note for note in report.client_notes
            ):
                continue
        items.append(_client_row(client, config_transport=transport))

    if report.dual_writer_warning:
        items.append(("DualWriter", _trunc(report.dual_writer_warning), "error"))
    if report.missing_auth_warning:
        items.append(("Auth", _trunc(report.missing_auth_warning), "error"))

    if report.client_notes:
        first = report.client_notes[0]
        if len(report.client_notes) == 1:
            items.append(("Notes", _trunc(first), "warning"))
        else:
            items.append(
                (
                    "Notes",
                    _trunc(f"{len(report.client_notes)} notes · {first}"),
                    "warning",
                )
            )

    return items
