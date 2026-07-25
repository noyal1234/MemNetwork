"""Stacked compression pipeline with per-stage inflation guards."""

from __future__ import annotations

from pathlib import Path

from brainkm.models.brain_config import BrainConfig, CompressionConfig
from brainkm.services.compression.classify import classify_content, split_subblocks
from brainkm.services.compression.prose import condense_prose
from brainkm.services.compression.rtk_lite import compress_tool_log
from brainkm.services.compression.types import (
    ENGINE_VERSION,
    ContentClass,
    PipelineResult,
    ProseIntensity,
    StageResult,
)
from brainkm.services.memory import token_count


def _apply_stage(
    text: str,
    stage: StageResult,
    *,
    inflation_guard: bool,
) -> tuple[str, StageResult]:
    if not inflation_guard:
        return stage.text, stage
    if stage.tokens_out >= stage.tokens_in and stage.skipped_reason is None:
        return text, StageResult(
            engine_id=stage.engine_id,
            text=text,
            tokens_in=stage.tokens_in,
            tokens_out=stage.tokens_in,
            skipped_reason="inflation_guard",
            latency_ms=stage.latency_ms,
            tee_path=stage.tee_path,
        )
    if stage.skipped_reason == "inflation_guard":
        return text, stage
    return stage.text, stage


def _run_class_engines(
    text: str,
    content_class: ContentClass,
    *,
    config: CompressionConfig,
    project_dir: Path | None,
    prose_intensity: ProseIntensity,
) -> tuple[str, list[StageResult], str | None]:
    stages: list[StageResult] = []
    tee_path: str | None = None
    current = text
    guard = config.inflation_guard

    if content_class in {"tool_log", "observation"} and config.rtk_lite_enabled:
        if content_class == "tool_log" or len(text) > 120:
            stage = compress_tool_log(current, project_dir=project_dir)
            current, stage = _apply_stage(current, stage, inflation_guard=guard)
            stages.append(stage)
            tee_path = stage.tee_path or tee_path

    if content_class == "error":
        # Keep first + last chunks of long traces
        lines = current.splitlines()
        if len(lines) > 40:
            trimmed = "\n".join(lines[:15] + ["[… traceback middle omitted …]"] + lines[-10:])
            tin, tout = token_count(current), token_count(trimmed)
            stage = StageResult(
                engine_id="error_trim",
                text=trimmed if (not guard or tout < tin) else current,
                tokens_in=tin,
                tokens_out=min(tin, tout) if guard and tout >= tin else tout,
                skipped_reason="inflation_guard" if guard and tout >= tin else None,
            )
            current = stage.text
            stages.append(stage)

    # Decision/rule: prose only when intensity allows (egress path sets this)
    if content_class in {"decision", "rule"} and prose_intensity == "off":
        return current, stages, tee_path

    if content_class in {
        "prose",
        "observation",
        "decision",
        "rule",
        "procedure",
        "tool_log",
    } and prose_intensity != "off":
        # Skip prose on pure tool_log after rtk unless residual natural language
        if content_class == "tool_log" and prose_intensity == "lite":
            return current, stages, tee_path
        stage = condense_prose(current, intensity=prose_intensity)
        current, stage = _apply_stage(current, stage, inflation_guard=guard)
        stages.append(stage)

    return current, stages, tee_path


def compress_text(
    text: str,
    *,
    kind: str | None = None,
    subtype: str | None = None,
    config: BrainConfig | CompressionConfig | None = None,
    project_dir: Path | None = None,
    prose_intensity: ProseIntensity | None = None,
    allow_decision_lossy: bool = False,
) -> PipelineResult:
    """Run content-class pipeline. Decision/rule lossy prose off unless allow_decision_lossy."""
    cfg = config
    if isinstance(cfg, BrainConfig):
        ccfg = cfg.compression
    elif isinstance(cfg, CompressionConfig):
        ccfg = cfg
    else:
        ccfg = CompressionConfig()

    tokens_in = token_count(text or "")
    if not ccfg.pipeline_enabled or not (text or "").strip():
        return PipelineResult(
            text=text or "",
            content_class=classify_content(text or "", kind=kind, subtype=subtype),
            tokens_in=tokens_in,
            tokens_out=tokens_in,
            engine_version=ccfg.engine_version or ENGINE_VERSION,
        )

    top_class = classify_content(text, kind=kind, subtype=subtype)
    intensity: ProseIntensity = prose_intensity or ccfg.prose_intensity  # type: ignore[assignment]
    if top_class in {"decision", "rule"} and not allow_decision_lossy:
        intensity = "off"

    # Sub-block path for mixed bodies
    blocks = split_subblocks(text)
    if len(blocks) > 1 and top_class in {"decision", "rule", "prose", "observation"}:
        parts: list[str] = []
        all_stages: list[StageResult] = []
        tee: str | None = None
        for block_class, segment in blocks:
            block_intensity = intensity
            if block_class in {"decision", "rule"} and not allow_decision_lossy:
                block_intensity = "off"
            out, stages, tee_path = _run_class_engines(
                segment,
                block_class,
                config=ccfg,
                project_dir=project_dir,
                prose_intensity=block_intensity,
            )
            parts.append(out)
            all_stages.extend(stages)
            tee = tee_path or tee
        merged = "".join(parts)
        return PipelineResult(
            text=merged,
            content_class=top_class,
            stages=all_stages,
            tokens_in=tokens_in,
            tokens_out=token_count(merged),
            tee_path=tee,
            engine_version=ccfg.engine_version or ENGINE_VERSION,
        )

    out, stages, tee = _run_class_engines(
        text,
        top_class,
        config=ccfg,
        project_dir=project_dir,
        prose_intensity=intensity,
    )

    # Optional extractive cap for write paths (never re-enter pipeline)
    if ccfg.write_time and token_count(out) > ccfg.max_body_tokens:
        from brainkm.services.compress import _extractive_cap

        before = out
        capped = _extractive_cap(out, max_tokens=ccfg.max_body_tokens)
        stages.append(
            StageResult(
                engine_id="extractive",
                text=capped,
                tokens_in=token_count(before),
                tokens_out=token_count(capped),
            )
        )
        out = capped

    # Optional LLMLingua (fail-open)
    if ccfg.llmlingua_enabled and token_count(out) >= ccfg.llmlingua_min_tokens:
        from brainkm.services.compression.llmlingua import try_llmlingua

        stage = try_llmlingua(out, rate=ccfg.llmlingua_rate)
        out, stage = _apply_stage(out, stage, inflation_guard=ccfg.inflation_guard)
        stages.append(stage)

    return PipelineResult(
        text=out,
        content_class=top_class,
        stages=stages,
        tokens_in=tokens_in,
        tokens_out=token_count(out),
        tee_path=tee,
        engine_version=ccfg.engine_version or ENGINE_VERSION,
    )
