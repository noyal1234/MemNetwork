"""Map McpDoctorReport → StatusPanel (label, value, state) rows for the Dashboard."""

from __future__ import annotations

import textwrap

from brainkm.services.mcp_doctor import ClientWireStatus, McpDoctorReport

# Compact single-line cells (client summaries).
_MAX_VALUE = 48
# Value column width after "Label: ◆ " — keep under typical panel (~64 cols).
_VALUE_WRAP = 46


def _trunc(text: str, limit: int = _MAX_VALUE) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _wrap_lines(text: str, *, width: int = _VALUE_WRAP) -> list[str]:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return ["—"]
    return textwrap.wrap(
        cleaned,
        width=max(20, width),
        break_long_words=True,
        break_on_hyphens=False,
    ) or ["—"]


def _note_rows(notes: list[str], *, state: str, label: str = "Notes") -> list[tuple[str, str, str]]:
    """One StatusPanel row block per note; continuation lines use an empty label."""
    rows: list[tuple[str, str, str]] = []
    for idx, note in enumerate(notes):
        if idx == 0:
            head = label
        elif label.lower() in {"tip", "probe"}:
            head = f"{label} {idx + 1}"
        else:
            head = f"Note {idx + 1}"
        for line_i, chunk in enumerate(_wrap_lines(note)):
            rows.append((head if line_i == 0 else "", chunk, state))
    return rows


def _short_health_fail(detail: str) -> str:
    """Humanize connection errors instead of dumping urlopen internals."""
    lower = (detail or "").lower()
    if "errno 61" in lower or "connection refused" in lower:
        return "FAIL · connection refused — start shared brain (serve)"
    if "timed out" in lower or "timeout" in lower:
        return "FAIL · health timeout"
    if "unreachable" in lower:
        return "FAIL · unreachable — is brainkm serve running?"
    return _trunc(f"FAIL · {detail}", limit=80)


_CLIENT_LABELS = {
    "antigravity": "agy",
    "cursor": "cursor",
    "claude": "claude",
    "codex": "codex",
    "generic": "generic",
}

# Doctor dry-runs / UI reminders — muted Probe, not warning Issues.
_INFO_NOTE_MARKERS = (
    "envelope ok",
    "hookSpecificOutput ok",
    "valid JSON stdout",
    "(ok if pack",
    "reminder (codex",
    "files alone cannot prove",
)


def _is_info_note(note: str) -> bool:
    lower = note.lower()
    return any(marker in lower for marker in _INFO_NOTE_MARKERS)


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
        if report.health_ok:
            items.append(("Health", "ok", "ok"))
        else:
            detail = report.health_detail or "unknown"
            items.extend(
                _note_rows([_short_health_fail(detail)], state="error", label="Health")
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
        if not client.present and client.client == "generic":
            continue
        items.append(_client_row(client, config_transport=transport))

    if report.dual_writer_warning:
        items.extend(
            _note_rows([report.dual_writer_warning], state="error", label="DualWriter")
        )
    if report.missing_auth_warning:
        items.extend(_note_rows([report.missing_auth_warning], state="error", label="Auth"))

    if report.client_notes:
        warnings = [n for n in report.client_notes if not _is_info_note(n)]
        infos = [n for n in report.client_notes if _is_info_note(n)]
        if warnings:
            items.extend(_note_rows(warnings, state="warning", label="Notes"))
        if infos and not warnings:
            # Reminders / dry-run probes — muted, not Issues chrome.
            items.extend(_note_rows(infos[:2], state="muted", label="Tip"))
        elif infos and warnings:
            # Keep tips after real warnings, still muted.
            items.extend(_note_rows(infos[:1], state="muted", label="Tip"))

    return items
