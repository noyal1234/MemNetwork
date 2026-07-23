"""Outbound injection / noise gate for agent-facing retrieval payloads.

Write paths already funnel through ``remember_neuron`` → ``sanitize_for_storage``.
Read paths (recall, context_pack, traverse linked memories / candidates, git
traces) must apply the same rules so legacy rows, imports, or bypassed writes
cannot inject into agents.

Threat-model note: this reuses ``sanitize_for_storage`` pattern matching
(secrets + prompt-injection block/strip rules). That is a *shared signal*, not
a perfect dual of store-vs-inject judgment — residual false-negative risk on
obfuscated phrasing is acknowledged; prefer omit-on-block over echo-on-doubt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from brainkm.adapters.redaction import SanitizeResult, sanitize_for_storage
from brainkm.services.quality import passes_stored_neuron_gate

GateReason = Literal["block", "strip", "noise"]

# Process-local pending counts flushed to session_activity by MCP handlers.
_pending: dict[GateReason, int] = {"block": 0, "strip": 0, "noise": 0}


@dataclass(frozen=True)
class OutboundText:
    """Cleaned title/body safe to surface to an agent, or blocked."""

    title: str
    content: str
    blocked: bool = False
    block_reason: str | None = None


def pending_gate_counts() -> dict[str, int]:
    """Snapshot of unflushed gate fires (block/strip/noise)."""
    return {k: int(v) for k, v in _pending.items()}


def _bump(reason: GateReason) -> None:
    _pending[reason] = int(_pending.get(reason, 0)) + 1


def filter_outbound_text(
    title: str,
    content: str | None,
    *,
    require_noise_gate: bool = True,
) -> OutboundText | None:
    """Return cleaned text, or ``None`` when the row must not be injected.

    Applies ``passes_stored_neuron_gate`` (noise/chrome) when ``require_noise_gate``
    is True, then ``sanitize_for_storage`` (secrets + prompt-injection).
    Blocked content is omitted entirely — never returned verbatim.

    Coverage: title + content only (tags/metadata are not agent-facing in MCP
    neuron payloads today). Procedure bodies are content strings; tool JSON is
    not returned by recall/pack as raw records.
    """
    title_s = title or ""
    content_s = content or ""
    if require_noise_gate and not passes_stored_neuron_gate(title=title_s, content=content_s):
        _bump("noise")
        return None
    gate = sanitize_for_storage(
        title_s,
        content_s,
        source="injection",
        mode="capture",
    )
    if gate.blocked:
        _bump("block")
        return None
    if gate.findings:
        _bump("strip")
    return OutboundText(title=gate.title, content=gate.content)


def sanitize_untrusted_agent_text(
    text: str,
    *,
    placeholder: str,
) -> str:
    """Sanitize free-form text (e.g. git subjects, traverse candidate labels).

    Unlike neuron gating, blocked text is replaced with ``placeholder`` so
    timeline / ambiguity structure can remain.
    """
    raw = (text or "").strip()
    if not raw:
        return raw
    gate: SanitizeResult = sanitize_for_storage(
        "",
        raw,
        source="injection",
        mode="capture",
    )
    if gate.blocked:
        _bump("block")
        return placeholder
    cleaned = (gate.content or "").strip()
    if gate.findings:
        _bump("strip")
    return cleaned if cleaned else placeholder


def flush_outbound_gate_events(
    conn: object,
    session_id: str | None = None,
) -> dict[str, int]:
    """Persist pending gate fires into ``session_activity`` and reset counters.

    ``kind='outbound_gate'``, ``tool_name`` is block|strip|noise, ``source`` is
    the fire count for that flush (encoded in tool_name suffix as ``block:N``).
    """
    from brainkm.services.audit import utc_now_iso
    from brainkm.services.memory import new_ulid
    from brainkm.services.session_activity import ANON_SESSION_ID

    flushed = pending_gate_counts()
    if not any(flushed.values()):
        return flushed
    sid = session_id or ANON_SESSION_ID
    now = utc_now_iso()
    for reason, count in flushed.items():
        if count <= 0:
            continue
        conn.execute(  # type: ignore[union-attr]
            """
            INSERT INTO session_activity (
              id, session_id, kind, node_id, tool_name, source, created_at
            ) VALUES (?, ?, 'outbound_gate', NULL, ?, 'injection', ?)
            """,
            (new_ulid(), sid, f"{reason}:{count}", now),
        )
        _pending[reason] = 0  # type: ignore[index]
    return flushed
