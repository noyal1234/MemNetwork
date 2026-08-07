"""Groq cloud distill diagnostics and reachability probes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from brainkm.config import get_settings
from brainkm.logging_config import get_logger
from brainkm.services.config_loader import config_path, load_brain_config

logger = get_logger("services.groq_advisor")

DEFAULT_PROBE_MODEL = "llama-3.3-70b-versatile"

FREE_TIER_HINT = (
    "Free tier (llama-3.3-70b-versatile): ~30 RPM, 1,000 RPD, 12K TPM, 100K TPD — "
    "enough for SessionEnd/PreCompact distill rounds"
)


@dataclass(frozen=True)
class GroqStatus:
    reachable: bool
    models: tuple[str, ...] = ()
    error: str | None = None
    rate_limited: bool = False


@dataclass(frozen=True)
class GroqDoctorReport:
    api_key_present: bool
    api_key_masked: str | None
    status: GroqStatus
    config_model: str | None
    config_base_url: str | None
    config_path: Path | None
    cloud_distill_acknowledged: bool = False
    distill_mode: str | None = None
    free_tier_hint: str = FREE_TIER_HINT


def is_rate_limit_error(error: str | None) -> bool:
    """True when an error string indicates HTTP 429 / rate_limit_exceeded."""
    if not error:
        return False
    lowered = error.lower()
    return (
        "429" in lowered
        or "rate limit" in lowered
        or "rate_limit" in lowered
        or "too many requests" in lowered
    )


def mask_api_key(api_key: str | None) -> str | None:
    """Return a masked preview of the API key for CLI display."""
    if not api_key:
        return None
    if len(api_key) <= 8:
        return "***"
    return f"{api_key[:4]}...{api_key[-4:]}"


def probe_groq(
    base_url: str,
    api_key: str | None,
    *,
    model: str | None = None,
) -> GroqStatus:
    """Check whether Groq chat completions work with the given API key.

    Uses a 1-token chat/completions call — the same API path distill uses.
    Listing ``GET /models`` is *not* used: some keys get 403 there even when
    chat succeeds (false "unreachable" / forced rules fallback).
    """
    if not api_key:
        return GroqStatus(reachable=False, error="GROQ_API_KEY not set")

    try:
        import httpx
    except ImportError:
        return GroqStatus(
            reachable=False,
            error="httpx not installed (pip install brainkm[cloud])",
        )

    probe_model = (model or DEFAULT_PROBE_MODEL).strip() or DEFAULT_PROBE_MODEL
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": probe_model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "temperature": 0,
    }
    try:
        response = httpx.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=5.0,
        )
        if response.status_code == 401:
            return GroqStatus(reachable=False, error="unauthorized (check GROQ_API_KEY)")
        if response.status_code == 429:
            retry = response.headers.get("retry-after")
            detail = _short_error_body(response)
            parts = ["rate limited (429)"]
            if retry:
                parts.append(f"retry-after {retry}s")
            if detail:
                parts.append(detail)
            return GroqStatus(
                reachable=False,
                error="; ".join(parts),
                rate_limited=True,
            )
        if response.status_code != 200:
            detail = _short_error_body(response)
            suffix = f": {detail}" if detail else ""
            return GroqStatus(
                reachable=False,
                error=f"HTTP {response.status_code}{suffix}",
                rate_limited=is_rate_limit_error(detail),
            )
        return GroqStatus(reachable=True, models=(probe_model,))
    except Exception as exc:
        logger.debug("Groq probe failed: %s", exc)
        return GroqStatus(reachable=False, error=str(exc))


def _short_error_body(response: object) -> str:
    """Best-effort short error snippet from an httpx response."""
    try:
        payload = response.json()  # type: ignore[attr-defined]
        err = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(err, dict):
            msg = str(err.get("message") or err.get("code") or "").strip()
            return msg[:120] if msg else ""
        if isinstance(err, str):
            return err[:120]
    except Exception:
        pass
    try:
        text = str(getattr(response, "text", "") or "").strip()
        return text[:120]
    except Exception:
        return ""


def build_groq_report(
    *,
    project_dir: Path | None = None,
    api_key: str | None = None,
) -> GroqDoctorReport:
    """Assemble Groq key, reachability, and config status."""
    # Settings.env_file=".env" is cwd-relative; configure/doctor often run with
    # --project-dir pointing elsewhere. Load that project's .env first.
    if api_key is None and project_dir is not None:
        from brainkm.config import apply_project_env

        apply_project_env(project_dir)
    resolved_key = api_key if api_key is not None else get_settings().groq_api_key
    cfg_path = config_path(project_dir)
    config_model: str | None = None
    base_url = "https://api.groq.com/openai/v1"
    cloud_ack = False
    distill_mode: str | None = None
    if cfg_path.is_file():
        cfg = load_brain_config(project_dir)
        config_model = cfg.groq.model
        base_url = cfg.groq.base_url
        cloud_ack = bool(cfg.capture.cloud_distill_acknowledged)
        distill_mode = cfg.capture.distill_mode

    status = probe_groq(base_url, resolved_key, model=config_model)
    return GroqDoctorReport(
        api_key_present=bool(resolved_key),
        api_key_masked=mask_api_key(resolved_key),
        status=status,
        config_model=config_model,
        config_base_url=base_url if cfg_path.is_file() else None,
        config_path=cfg_path if cfg_path.is_file() else None,
        cloud_distill_acknowledged=cloud_ack,
        distill_mode=distill_mode,
    )


def format_groq_report(report: GroqDoctorReport) -> str:
    """Render Groq doctor output for CLI."""
    lines: list[str] = []
    if report.api_key_present:
        lines.append(f"API key: present ({report.api_key_masked})")
    else:
        lines.append("API key: missing — set GROQ_API_KEY in the environment or .env")

    if report.status.reachable:
        lines.append("Groq reachable: yes (chat/completions probe)")
        if report.status.models:
            lines.append(f"Probed model: {report.status.models[0]}")
    else:
        err = f" ({report.status.error})" if report.status.error else ""
        lines.append(f"Groq reachable: no{err}")
        if report.status.rate_limited:
            lines.append(
                "Rate limit: HTTP 429 — wait for retry-after / x-ratelimit-reset-* headers"
            )

    if report.config_model is None:
        lines.append("Config model: (no .brain/config.json)")
    else:
        lines.append(f"Config model: {report.config_model}")
        if report.config_base_url:
            lines.append(f"Config base_url: {report.config_base_url}")

    if report.distill_mode == "groq":
        if report.cloud_distill_acknowledged:
            lines.append("Cloud distill consent: acknowledged")
        else:
            lines.append(
                "Cloud distill consent: MISSING — set "
                "capture.cloud_distill_acknowledged=true (or re-run wizard) "
                "before transcripts leave the machine"
            )
    else:
        lines.append(f"Cloud distill consent: n/a (distill_mode={report.distill_mode or 'unset'})")

    lines.append(f"Hint: {report.free_tier_hint}")
    lines.append(
        'To use cloud distill: set capture.distill_mode to "groq" and '
        "capture.cloud_distill_acknowledged to true in .brain/config.json"
    )
    return "\n".join(lines)
