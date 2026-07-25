"""Cache-aware cost model, TTL decay, gap-time bands, context-rot, bump window."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Sequence

# Default published cache TTL class (~5 minutes) shared across hosts.
DEFAULT_CACHE_TTL_SECONDS = 300.0

# Synthetic session shape until transcript-derived weights exist (cost_bench parity).
SYNTHETIC_SESSION_START = 1
SYNTHETIC_PRE_TOOL = 8


@dataclass(frozen=True)
class PriceTable:
    input_per_mtok: float = 3.0
    cache_read_per_mtok: float = 0.30  # ~90% discount
    cache_write_per_mtok: float = 3.75  # ~1.25x write premium
    output_per_mtok: float = 15.0


@dataclass
class GapSample:
    gap_seconds: float


@dataclass
class HitBands:
    p_warm: float
    p_cold: float
    ttl_seconds: float
    n_samples: int
    weight_source: str = "synthetic"


@dataclass
class CostBreakdown:
    write_cost: float
    warm_read_cost: float
    cold_reread_cost: float
    total: float
    weight_source: str
    surface: str


@dataclass
class ContextRotStats:
    unique_neuron_tokens: int
    total_injected_tokens: int
    redundant_reinject_rate: float
    context_growth_rate: float

    @property
    def unique_neuron_token_density(self) -> float:
        if self.total_injected_tokens <= 0:
            return 1.0
        return self.unique_neuron_tokens / self.total_injected_tokens


@dataclass
class BumpWindow:
    n_seconds: float
    p95_session_duration: float
    p95_frozen_refresh: float
    cache_ttl: float


def parse_iso(ts: str) -> datetime | None:
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def gaps_from_timestamps(timestamps: Sequence[str | float | datetime]) -> list[float]:
    """Return inter-event gaps in seconds (sorted chronological)."""
    instants: list[float] = []
    for item in timestamps:
        if isinstance(item, datetime):
            instants.append(item.timestamp())
        elif isinstance(item, (int, float)):
            instants.append(float(item))
        else:
            dt = parse_iso(str(item))
            if dt is not None:
                instants.append(dt.timestamp())
    instants.sort()
    return [instants[i] - instants[i - 1] for i in range(1, len(instants))]


def hit_bands_from_gaps(
    gaps: Sequence[float],
    *,
    ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
    weight_source: str = "transcript_session_shape",
) -> HitBands:
    if not gaps:
        # Conservative synthetic prior until Phase 0 corpus exists
        return HitBands(
            p_warm=0.55,
            p_cold=0.45,
            ttl_seconds=ttl_seconds,
            n_samples=0,
            weight_source="synthetic",
        )
    warm = sum(1 for g in gaps if g <= ttl_seconds)
    n = len(gaps)
    p_warm = warm / n
    return HitBands(
        p_warm=p_warm,
        p_cold=1.0 - p_warm,
        ttl_seconds=ttl_seconds,
        n_samples=n,
        weight_source=weight_source,
    )


def warm_credit_tokens(
    tokens_in_history: int,
    *,
    gap_since_activity: float,
    ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
) -> int:
    """TTL-decayed warm-read credit; 0 if gap exceeds TTL."""
    if tokens_in_history <= 0:
        return 0
    if gap_since_activity > ttl_seconds:
        return 0
    return tokens_in_history


def usd_for_tokens(tokens: int, price_per_mtok: float) -> float:
    return (tokens / 1_000_000.0) * price_per_mtok


def mode_a_write_cost(tokens_appended: int, prices: PriceTable | None = None) -> float:
    prices = prices or PriceTable()
    return usd_for_tokens(tokens_appended, prices.input_per_mtok)


def mode_a_lifetime_cost(
    tokens_appended: int,
    warm_read_token_turns: Sequence[int],
    *,
    prices: PriceTable | None = None,
) -> CostBreakdown:
    """Write at full price + TTL-filtered warm reads at cache-read price."""
    prices = prices or PriceTable()
    write = mode_a_write_cost(tokens_appended, prices)
    warm = sum(usd_for_tokens(t, prices.cache_read_per_mtok) for t in warm_read_token_turns)
    return CostBreakdown(
        write_cost=write,
        warm_read_cost=warm,
        cold_reread_cost=0.0,
        total=write + warm,
        weight_source="lifetime_ttl",
        surface="mode_a",
    )


def mode_s_expected_cost(
    tokens: int,
    bands: HitBands,
    *,
    prices: PriceTable | None = None,
) -> CostBreakdown:
    prices = prices or PriceTable()
    warm = usd_for_tokens(tokens, prices.cache_read_per_mtok) * bands.p_warm
    cold = usd_for_tokens(tokens, prices.input_per_mtok) * bands.p_cold
    return CostBreakdown(
        write_cost=cold,
        warm_read_cost=warm,
        cold_reread_cost=cold,
        total=warm + cold,
        weight_source=bands.weight_source,
        surface="mode_s",
    )


def pct_reduction(baseline: float, candidate: float) -> float:
    if baseline <= 0:
        return 0.0
    return (baseline - candidate) / baseline * 100.0


def context_rot_stats(
    *,
    injected_neuron_ids_per_turn: Sequence[Sequence[str]],
    token_by_neuron: dict[str, int],
) -> ContextRotStats:
    seen: set[str] = set()
    total_tokens = 0
    unique_tokens = 0
    reinject_hits = 0
    reinject_total = 0
    prev_total = 0
    growths: list[float] = []
    for turn in injected_neuron_ids_per_turn:
        turn_tokens = 0
        for nid in turn:
            tok = token_by_neuron.get(nid, 0)
            turn_tokens += tok
            reinject_total += 1
            if nid in seen:
                reinject_hits += 1
            else:
                seen.add(nid)
                unique_tokens += tok
        total_tokens += turn_tokens
        growths.append(float(turn_tokens - prev_total) if prev_total else float(turn_tokens))
        prev_total = turn_tokens
    rate = (reinject_hits / reinject_total) if reinject_total else 0.0
    growth = statistics.mean(growths) if growths else 0.0
    return ContextRotStats(
        unique_neuron_tokens=unique_tokens,
        total_injected_tokens=total_tokens,
        redundant_reinject_rate=rate,
        context_growth_rate=growth,
    )


def bump_window_seconds(
    session_durations: Sequence[float],
    frozen_refresh_gaps: Sequence[float],
    *,
    cache_ttl: float = DEFAULT_CACHE_TTL_SECONDS,
) -> BumpWindow:
    def p95(values: Sequence[float]) -> float:
        if not values:
            return cache_ttl
        ordered = sorted(values)
        idx = min(len(ordered) - 1, max(0, math.ceil(0.95 * len(ordered)) - 1))
        return float(ordered[idx])

    p95_sess = p95(session_durations)
    p95_refresh = p95(frozen_refresh_gaps) if frozen_refresh_gaps else 0.0
    n = max(p95_sess, p95_refresh, cache_ttl)
    return BumpWindow(
        n_seconds=n,
        p95_session_duration=p95_sess,
        p95_frozen_refresh=p95_refresh,
        cache_ttl=cache_ttl,
    )


@dataclass
class SessionShapeWeights:
    session_start: float = float(SYNTHETIC_SESSION_START)
    pre_tool: float = float(SYNTHETIC_PRE_TOOL)
    mcp_packs: float = 2.0
    weight_source: str = "synthetic"


def rollup_expected_savings_pct(
    *,
    mode_a_write_baseline: float,
    mode_a_write_candidate: float,
    mode_s_baseline: float,
    mode_s_candidate: float,
    weights: SessionShapeWeights | None = None,
) -> tuple[float, str]:
    weights = weights or SessionShapeWeights()
    w_a = weights.pre_tool + weights.mcp_packs
    w_s = weights.session_start
    base = mode_a_write_baseline * w_a + mode_s_baseline * w_s
    cand = mode_a_write_candidate * w_a + mode_s_candidate * w_s
    return pct_reduction(base, cand), weights.weight_source
