"""Scale bench — R@5 + latency at 1k / 10k / 50k synthetic neurons."""

from __future__ import annotations

import time
from pathlib import Path

from brainkm.bench.results import BenchCaseResult, BenchSuiteResult
from brainkm.config import set_skip_rolling_scores
from brainkm.models.brain_config import BrainConfig, RecallConfig
from brainkm.services.bench_db import (
    cleanup_ephemeral_project,
    ensure_fixture_neuron,
    ephemeral_project_brain,
)
from brainkm.services.context_pack import compile_context_pack
from brainkm.services.ir_metrics import precision_at_k
from brainkm.services.recall import recall_live

DEFAULT_SIZES = (1_000, 10_000, 50_000)
# Keep default CI/dev runs affordable; full 50k via --sizes or env.
DEFAULT_SIZES_FAST = (1_000, 10_000)
_PROBE_QUERIES = (
    ("auth jwt jose middleware decision", "scale_gold_auth"),
    ("sqlite wal project brain store", "scale_gold_db"),
    ("token budget 1500 pack cap", "scale_gold_budget"),
    ("graphify extract import code graph", "scale_gold_graph"),
    ("session end distill transcript neurons", "scale_gold_capture"),
)


def _seed_scale_corpus(conn, size: int) -> None:
    """Deterministic synthetic corpus with 5 gold needles."""
    gold = {
        "scale_gold_auth": (
            "Auth uses JWT with jose middleware",
            "Decision: JWT via jose for Edge compatibility; sessions deprecated.",
        ),
        "scale_gold_db": (
            "SQLite WAL is the project brain store",
            "Local SQLite with WAL mode; Postgres deferred for V1.",
        ),
        "scale_gold_budget": (
            "Hard pack token budget is 1500",
            "context_pack truncates greedily under a 1500 token cap.",
        ),
        "scale_gold_graph": (
            "Graphify extract plus import builds the code graph",
            "AST nodes and edges come from Graphify sync into brain.db.",
        ),
        "scale_gold_capture": (
            "SessionEnd distill fills neurons from transcripts",
            "Hooks capture session transcripts; remember is pin/correct only.",
        ),
    }
    for node_id, (title, content) in gold.items():
        ensure_fixture_neuron(
            conn,
            node_id=node_id,
            title=title,
            content=content,
            kind="memory",
            subtype="decision",
        )
    # Fill remaining slots with noise.
    for i in range(size - len(gold)):
        ensure_fixture_neuron(
            conn,
            node_id=f"scale_noise_{i:06d}",
            title=f"noise topic {i % 97} filler {i}",
            content=(
                f"Synthetic filler neuron {i}. Unrelated to auth, sqlite, budget, "
                f"graphify, or session distill. Tag={i % 13}."
            ),
            kind="memory",
            subtype="context",
        )
    conn.commit()


def run_scale_suite(
    _db_path: Path | None = None,
    *,
    sizes: tuple[int, ...] | None = None,
    fast: bool = True,
) -> BenchSuiteResult:
    """Measure retrieval quality + latency as corpus size grows."""
    del _db_path
    size_list = sizes or (DEFAULT_SIZES_FAST if fast else DEFAULT_SIZES)
    cases: list[BenchCaseResult] = []
    set_skip_rolling_scores(True)
    try:
        for size in size_list:
            conn, _db, project = ephemeral_project_brain()
            try:
                _seed_scale_corpus(conn, size)
                recall_cfg = RecallConfig(abstain_on_low_confidence=False)
                cfg = BrainConfig(recall=recall_cfg)
                hits = 0
                p5_vals: list[float] = []
                recall_ms: list[float] = []
                pack_ms: list[float] = []
                for query, gold_id in _PROBE_QUERIES:
                    t0 = time.perf_counter()
                    result = recall_live(
                        conn,
                        query,
                        limit=5,
                        recall=recall_cfg,
                        project_dir=project,
                    )
                    recall_ms.append((time.perf_counter() - t0) * 1000.0)
                    ranked = [n.node_id for n in result.nodes]
                    if gold_id in ranked[:5]:
                        hits += 1
                    p5_vals.append(precision_at_k(ranked, {gold_id}, 5))

                    t1 = time.perf_counter()
                    compile_context_pack(
                        conn, query, config=cfg, project_dir=project
                    )
                    pack_ms.append((time.perf_counter() - t1) * 1000.0)

                n = len(_PROBE_QUERIES)
                r5 = hits / n
                mean_p5 = sum(p5_vals) / n
                p95_recall = sorted(recall_ms)[max(0, int(0.95 * (n - 1)))]
                p95_pack = sorted(pack_ms)[max(0, int(0.95 * (n - 1)))]
                # Soft floors: quality must stay high; latency grows with size.
                quality_ok = r5 >= 0.8
                cases.append(
                    BenchCaseResult(
                        name=f"size/{size}/recall_at_5",
                        passed=quality_ok,
                        detail=f"{r5:.3f} ({hits}/{n})",
                    )
                )
                cases.append(
                    BenchCaseResult(
                        name=f"size/{size}/precision_at_5",
                        passed=True,
                        detail=f"{mean_p5:.3f}",
                    )
                )
                cases.append(
                    BenchCaseResult(
                        name=f"size/{size}/recall_p95_ms",
                        passed=True,
                        detail=f"{p95_recall:.1f}",
                    )
                )
                cases.append(
                    BenchCaseResult(
                        name=f"size/{size}/pack_p95_ms",
                        passed=True,
                        detail=f"{p95_pack:.1f}",
                    )
                )
            finally:
                cleanup_ephemeral_project(project, conn)
    finally:
        set_skip_rolling_scores(False)

    passed = sum(1 for c in cases if c.passed)
    return BenchSuiteResult(
        suite="scale", passed=passed, total=len(cases), cases=cases
    )


def format_scale_summary(result: BenchSuiteResult) -> str:
    lines = ["Scale (synthetic corpus growth):"]
    for case in result.cases:
        if case.name.endswith("/recall_at_5"):
            size = case.name.split("/")[1]
            p95 = next(
                (
                    c.detail
                    for c in result.cases
                    if c.name == f"size/{size}/recall_p95_ms"
                ),
                "?",
            )
            lines.append(f"  n={size}: R@5={case.detail} recall_p95_ms={p95}")
    return "\n".join(lines)
