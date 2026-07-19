"""Cost-per-session model — injected tokens, distill tokens, $/year estimate."""

from __future__ import annotations

from pathlib import Path

from brainkm.bench.results import BenchCaseResult, BenchSuiteResult
from brainkm.config import set_skip_rolling_scores
from brainkm.models.brain_config import BrainConfig
from brainkm.services.bench_db import (
    cleanup_ephemeral_project,
    ensure_fixture_neuron,
    ephemeral_project_brain,
)
from brainkm.services.context_pack import compile_context_pack
from brainkm.services.memory import token_count
from brainkm.services.snapshot import build_frozen_snapshot

# Published list prices (USD / 1M tokens) for rough annualization — not billed invoices.
_PRICE_TABLE = {
    "claude-sonnet": {"input": 3.0, "output": 15.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "local": {"input": 0.0, "output": 0.0},
}

# Typical coding-agent session hook fire counts (conservative mid).
_SESSION_START_PACKS = 1
_PRE_TOOL_PACKS = 8
_SESSIONS_PER_YEAR = 250


def run_cost_suite(
    _db_path: Path | None = None,
    *,
    model: str = "claude-sonnet",
    sessions_per_year: int = _SESSIONS_PER_YEAR,
) -> BenchSuiteResult:
    """Estimate tokens injected + distill overhead per session and $/year."""
    del _db_path
    set_skip_rolling_scores(True)
    conn, _db, project = ephemeral_project_brain()
    cases: list[BenchCaseResult] = []
    try:
        for i in range(40):
            ensure_fixture_neuron(
                conn,
                node_id=f"cost_n_{i}",
                title=f"decision {i}: architecture note",
                content=(
                    f"Durable project fact {i}. Prefer local SQLite, MCP tools, "
                    f"and ≤1500-token packs. Tag={i}."
                ),
                kind="memory",
                subtype="decision" if i % 3 == 0 else "fact",
            )
        conn.commit()
        cfg = BrainConfig()

        # SessionStart frozen pack
        snap = build_frozen_snapshot(conn, "cost-session", cfg, context_hint="auth jwt")
        start_tokens = token_count(snap.pack_text or "")

        # PreToolUse context packs (average of a few probes)
        probes = (
            "auth jwt middleware",
            "sqlite wal brain",
            "graphify sync",
            "token budget pack",
        )
        pre_tool_sizes: list[int] = []
        for q in probes:
            pack = compile_context_pack(conn, q, config=cfg, project_dir=project)
            pre_tool_sizes.append(token_count(pack.pack_text or ""))
        mean_pre = sum(pre_tool_sizes) / len(pre_tool_sizes)

        injected = (
            _SESSION_START_PACKS * start_tokens + _PRE_TOOL_PACKS * mean_pre
        )
        # Distill: assume ~2k tokens of transcript summarized to ~400 tokens out.
        distill_in = 2000
        distill_out = 400
        distill_tokens = distill_in + distill_out

        prices = _PRICE_TABLE.get(model) or _PRICE_TABLE["claude-sonnet"]
        # Injection is model-input; distill is input+output of a small summarizer.
        cost_per_session = (
            (injected / 1_000_000.0) * prices["input"]
            + (distill_in / 1_000_000.0) * prices["input"]
            + (distill_out / 1_000_000.0) * prices["output"]
        )
        cost_per_year = cost_per_session * sessions_per_year

        cases = [
            BenchCaseResult(
                name="session_start_tokens",
                passed=start_tokens <= cfg.budget.total_tokens,
                detail=f"{start_tokens} (cap={cfg.budget.total_tokens})",
            ),
            BenchCaseResult(
                name="mean_pre_tool_tokens",
                passed=mean_pre <= cfg.budget.total_tokens,
                detail=f"{mean_pre:.0f}",
            ),
            BenchCaseResult(
                name="injected_tokens_per_session",
                passed=injected <= 20_000,
                detail=(
                    f"{injected:.0f} "
                    f"(start×{_SESSION_START_PACKS} + pre_tool×{_PRE_TOOL_PACKS})"
                ),
            ),
            BenchCaseResult(
                name="distill_tokens_per_session",
                passed=True,
                detail=f"{distill_tokens} (in={distill_in} out={distill_out})",
            ),
            BenchCaseResult(
                name="usd_per_session",
                passed=True,
                detail=f"${cost_per_session:.4f} model={model}",
            ),
            BenchCaseResult(
                name="usd_per_year",
                passed=True,
                detail=(
                    f"${cost_per_year:.2f} "
                    f"({sessions_per_year} sessions/yr, model={model})"
                ),
            ),
        ]
    finally:
        cleanup_ephemeral_project(project, conn)
        set_skip_rolling_scores(False)

    passed = sum(1 for c in cases if c.passed)
    return BenchSuiteResult(suite="cost", passed=passed, total=len(cases), cases=cases)


def format_cost_summary(result: BenchSuiteResult) -> str:
    injected = next(
        (c.detail for c in result.cases if c.name == "injected_tokens_per_session"),
        "?",
    )
    yearly = next(
        (c.detail for c in result.cases if c.name == "usd_per_year"), "?"
    )
    return (
        f"Cost model: injected/session={injected}; annual={yearly}. "
        "Prices are public list rates for modeling only — not invoices."
    )
