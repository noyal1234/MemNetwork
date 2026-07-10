"""Groq cloud distill diagnostics and reachability probes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from brainkm.config import get_settings
from brainkm.logging_config import get_logger
from brainkm.services.config_loader import config_path, load_brain_config

logger = get_logger("services.groq_advisor")

FREE_TIER_HINT = (
    "Free tier (llama-3.3-70b-versatile): ~30 RPM, 1,000 RPD, 12K TPM, 100K TPD — "
    "enough for SessionEnd/PreCompact distill rounds"
)


@dataclass(frozen=True)
class GroqStatus:
    reachable: bool
    models: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class GroqDoctorReport:
    api_key_present: bool
    api_key_masked: str | None
    status: GroqStatus
    config_model: str | None
    config_base_url: str | None
    config_path: Path | None
    free_tier_hint: str = FREE_TIER_HINT


def mask_api_key(api_key: str | None) -> str | None:
    """Return a masked preview of the API key for CLI display."""
    if not api_key:
        return None
    if len(api_key) <= 8:
        return "***"
    return f"{api_key[:4]}...{api_key[-4:]}"


def probe_groq(base_url: str, api_key: str | None) -> GroqStatus:
    """Check whether Groq is reachable with the given API key."""
    if not api_key:
        return GroqStatus(reachable=False, error="GROQ_API_KEY not set")

    try:
        import httpx
    except ImportError:
        return GroqStatus(reachable=False, error="httpx not installed (pip install brainkm[cloud])")

    url = f"{base_url.rstrip('/')}/models"
    try:
        response = httpx.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=5.0,
        )
        if response.status_code == 401:
            return GroqStatus(reachable=False, error="unauthorized (check GROQ_API_KEY)")
        if response.status_code == 429:
            return GroqStatus(reachable=False, error="rate limited (429)")
        if response.status_code != 200:
            return GroqStatus(reachable=False, error=f"HTTP {response.status_code}")
        payload = response.json()
        models = tuple(
            str(item.get("id", ""))
            for item in payload.get("data", [])
            if item.get("id")
        )
        return GroqStatus(reachable=True, models=models)
    except Exception as exc:
        logger.debug("Groq probe failed: %s", exc)
        return GroqStatus(reachable=False, error=str(exc))


def build_groq_report(
    *,
    project_dir: Path | None = None,
    api_key: str | None = None,
) -> GroqDoctorReport:
    """Assemble Groq key, reachability, and config status."""
    resolved_key = api_key if api_key is not None else get_settings().groq_api_key
    cfg_path = config_path(project_dir)
    config_model: str | None = None
    base_url = "https://api.groq.com/openai/v1"
    if cfg_path.is_file():
        cfg = load_brain_config(project_dir)
        config_model = cfg.groq.model
        base_url = cfg.groq.base_url

    status = probe_groq(base_url, resolved_key)
    return GroqDoctorReport(
        api_key_present=bool(resolved_key),
        api_key_masked=mask_api_key(resolved_key),
        status=status,
        config_model=config_model,
        config_base_url=base_url if cfg_path.is_file() else None,
        config_path=cfg_path if cfg_path.is_file() else None,
    )


def format_groq_report(report: GroqDoctorReport) -> str:
    """Render Groq doctor output for CLI."""
    lines: list[str] = []
    if report.api_key_present:
        lines.append(f"API key: present ({report.api_key_masked})")
    else:
        lines.append("API key: missing — set GROQ_API_KEY in the environment or .env")

    if report.status.reachable:
        lines.append("Groq reachable: yes")
        if report.status.models:
            preview = ", ".join(report.status.models[:8])
            more = f" (+{len(report.status.models) - 8} more)" if len(report.status.models) > 8 else ""
            lines.append(f"Available models: {preview}{more}")
    else:
        err = f" ({report.status.error})" if report.status.error else ""
        lines.append(f"Groq reachable: no{err}")

    if report.config_model is None:
        lines.append("Config model: (no .brain/config.json)")
    else:
        lines.append(f"Config model: {report.config_model}")
        if report.config_base_url:
            lines.append(f"Config base_url: {report.config_base_url}")

    lines.append(f"Hint: {report.free_tier_hint}")
    lines.append(
        "To use cloud distill: set capture.distill_mode to \"groq\" in .brain/config.json"
    )
    return "\n".join(lines)
