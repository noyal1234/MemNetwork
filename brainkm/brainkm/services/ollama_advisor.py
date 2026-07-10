"""Hardware-aware Ollama model recommendations and reachability probes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from brainkm.logging_config import get_logger
from brainkm.models.brain_config import BrainConfig
from brainkm.services.config_loader import config_path, load_brain_config
from brainkm.services.hardware import HardwareProfile, detect_hardware

logger = get_logger("services.ollama_advisor")


@dataclass(frozen=True)
class ModelRecommendation:
    model: str
    tier: str
    rationale: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class OllamaStatus:
    reachable: bool
    installed_models: tuple[str, ...] = ()


@dataclass(frozen=True)
class DoctorReport:
    profile: HardwareProfile
    recommendation: ModelRecommendation
    ollama: OllamaStatus
    config_model: str | None
    config_path: Path | None


def recommend_model(profile: HardwareProfile) -> ModelRecommendation:
    """Pick an Ollama model tier from host RAM, CPU, and GPU acceleration."""
    ram = profile.total_ram_gb
    warnings: list[str] = []

    if ram > 0 and ram < 8:
        return ModelRecommendation(
            model="qwen2.5:1.5b-instruct-q4_K_M",
            tier="minimal",
            rationale=(
                f"Under 8 GB RAM ({ram} GB detected) — use the smallest Qwen2.5 "
                "model or distill_mode: rules for reliability"
            ),
            warnings=tuple(warnings),
        )

    if profile.has_gpu_accel and ram >= 32:
        return ModelRecommendation(
            model="qwen2.5:14b-instruct-q4_K_M",
            tier="large",
            rationale=(
                f"{ram} GB RAM with GPU acceleration — 14B quantized fits unified "
                "memory / CUDA and improves distill quality"
            ),
            warnings=tuple(warnings),
        )

    if ram > 16 and (profile.has_gpu_accel or profile.cpu_cores >= 8):
        return ModelRecommendation(
            model="qwen2.5:7b-instruct-q4_K_M",
            tier="medium",
            rationale=(
                f"{ram} GB RAM with "
                f"{'GPU acceleration' if profile.has_gpu_accel else f'{profile.cpu_cores} CPU cores'} "
                "— 7B quantized balances quality and latency"
            ),
            warnings=tuple(warnings),
        )

    ram_label = f"{ram} GB" if ram > 0 else "unknown RAM"
    gpu_note = (
        "with Apple Silicon / CUDA"
        if profile.has_gpu_accel
        else f", {profile.cpu_cores} cores, no GPU acceleration"
    )
    return ModelRecommendation(
        model="qwen2.5:3b",
        tier="small",
        rationale=(
            f"{ram_label} {gpu_note} — Qwen2.5 3B keeps inference practical "
            "while following distill instructions well"
        ),
        warnings=tuple(warnings),
    )


def probe_ollama(base_url: str) -> OllamaStatus:
    """Check whether Ollama is reachable and list installed models."""
    try:
        import httpx
    except ImportError:
        return OllamaStatus(reachable=False)

    url = f"{base_url.rstrip('/')}/api/tags"
    try:
        response = httpx.get(url, timeout=2.0)
        if response.status_code != 200:
            return OllamaStatus(reachable=False)
        payload = response.json()
        models = tuple(
            str(item.get("name", ""))
            for item in payload.get("models", [])
            if item.get("name")
        )
        return OllamaStatus(reachable=True, installed_models=models)
    except Exception:
        return OllamaStatus(reachable=False)


def resolve_ollama_model(config: BrainConfig) -> str:
    """Return the model name to use for distill (auto-select or configured)."""
    configured = config.ollama.model
    if not config.ollama.auto_select_model:
        return configured

    profile = detect_hardware()
    if profile.total_ram_gb <= 0:
        logger.warning(
            "auto_select_model enabled but RAM unknown (install brainkm[ollama]); "
            "using configured model %s",
            configured,
        )
        return configured

    recommendation = recommend_model(profile)
    if recommendation.model != configured:
        logger.info(
            "auto_select_model: using %s (tier=%s) instead of configured %s",
            recommendation.model,
            recommendation.tier,
            configured,
        )
    return recommendation.model


def build_doctor_report(
    *,
    project_dir: Path | None = None,
    profile: HardwareProfile | None = None,
) -> DoctorReport:
    """Assemble hardware, recommendation, Ollama, and config status."""
    resolved_profile = profile or detect_hardware()
    recommendation = recommend_model(resolved_profile)

    cfg_path = config_path(project_dir)
    config_model: str | None = None
    base_url = "http://127.0.0.1:11434"
    if cfg_path.is_file():
        cfg = load_brain_config(project_dir)
        config_model = cfg.ollama.model
        base_url = cfg.ollama.base_url

    ollama = probe_ollama(base_url)
    return DoctorReport(
        profile=resolved_profile,
        recommendation=recommendation,
        ollama=ollama,
        config_model=config_model,
        config_path=cfg_path if cfg_path.is_file() else None,
    )


def format_doctor_report(report: DoctorReport) -> str:
    """Render doctor output for CLI."""
    profile = report.profile
    rec = report.recommendation
    lines = [
        (
            f"Hardware: {profile.total_ram_gb} GB RAM, {profile.cpu_cores} cores, "
            f"{profile.platform}/{profile.arch}, gpu_accel={profile.has_gpu_accel}"
        ),
        f"Recommended model: {rec.model} (tier={rec.tier})",
        f"  rationale: {rec.rationale}",
    ]
    for warning in rec.warnings:
        lines.append(f"  warning: {warning}")

    lines.append(f"Ollama reachable: {'yes' if report.ollama.reachable else 'no'}")
    if report.ollama.installed_models:
        lines.append(f"Installed models: {', '.join(report.ollama.installed_models)}")
    elif report.ollama.reachable:
        lines.append("Installed models: (none)")

    if report.config_model is None:
        lines.append("Config model: (no .brain/config.json)")
    elif report.config_model == rec.model:
        lines.append(f"Config model: {report.config_model}  (matches recommendation)")
    else:
        lines.append(
            f"Config model: {report.config_model}  (differs — run "
            f"`brainkm ollama doctor --apply` or set ollama.model to {rec.model!r})"
        )

    if report.config_model and rec.model not in report.ollama.installed_models:
        if report.ollama.reachable:
            lines.append(f"Hint: ollama pull {rec.model}")

    return "\n".join(lines)


def apply_recommended_model(
    *,
    project_dir: Path | None = None,
    recommendation: ModelRecommendation | None = None,
) -> Path:
    """Write recommended model into .brain/config.json; return config path."""
    cfg_path = config_path(project_dir)
    if not cfg_path.is_file():
        msg = f"config not found: {cfg_path}"
        raise FileNotFoundError(msg)

    rec = recommendation or recommend_model(detect_hardware())
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    ollama_section = data.setdefault("ollama", {})
    ollama_section["model"] = rec.model
    cfg_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    logger.info("Updated %s ollama.model -> %s", cfg_path, rec.model)
    return cfg_path
