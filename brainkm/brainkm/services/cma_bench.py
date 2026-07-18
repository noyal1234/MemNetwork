"""Common Memory Axes (CMA) scorecard — architecture-aware public comparison."""

from __future__ import annotations

import json
import statistics
import time
from collections import defaultdict
from importlib import resources
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
from brainkm.services.memory import new_ulid, supersede_neuron
from brainkm.services.recall import recall_live
from brainkm.services.search import fts_search_nodes, traverse


def _load_fixture(path: Path | None = None) -> dict:
    if path is not None:
        return json.loads(path.read_text(encoding="utf-8"))
    fixtures = resources.files("brainkm.bench.fixtures")
    for name in ("cma_v3.json", "cma_v2.json", "cma_v1.json"):
        candidate = fixtures.joinpath(name)
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))
    msg = "CMA fixture not found (expected cma_v3.json, cma_v2.json, or cma_v1.json)"
    raise FileNotFoundError(msg)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    idx = min(len(ordered) - 1, max(0, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[idx]


def _seed_corpus(conn, fixture: dict) -> None:
    for node in fixture.get("corpus", []):
        ensure_fixture_neuron(
            conn,
            node_id=node["id"],
            title=node["title"],
            content=node.get("content"),
            kind=node.get("kind", "memory"),
            subtype=node.get("subtype"),
        )
        path = node.get("path")
        tags = node.get("tags")
        if path or tags:
            if path:
                conn.execute("UPDATE nodes SET path = ? WHERE id = ?", (path, node["id"]))
            if tags is not None:
                conn.execute(
                    "UPDATE nodes SET tags = ? WHERE id = ?",
                    (json.dumps(tags, separators=(",", ":")), node["id"]),
                )

    now = "2026-01-01T00:00:00"
    for edge in fixture.get("edges", []):
        conn.execute(
            """
            INSERT OR IGNORE INTO edges
              (id, from_id, to_id, relationship, weight, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1.0, ?, ?)
            """,
            (
                new_ulid(),
                edge["from_id"],
                edge["to_id"],
                edge.get("relationship", "related"),
                now,
                now,
            ),
        )

    for pair in fixture.get("supersede", []):
        old_id = pair["old_id"]
        new_id = pair["new_id"]
        row = conn.execute(
            "SELECT valid_until FROM nodes WHERE id = ?", (old_id,)
        ).fetchone()
        if row is not None and row[0] is None:
            supersede_neuron(conn, old_id, replacement_id=new_id)

    conn.commit()


def _gold_hit(node_ids: list[str], expected: list[str], k: int) -> bool:
    top = set(node_ids[:k])
    return bool(top & set(expected))


def _title_scan_hit(conn, query: str, expected: list[str], k: int = 5) -> bool:
    """Naive baseline: rank titles by overlapping query tokens (no FTS BM25)."""
    tokens = [t.lower() for t in query.split() if len(t) > 2]
    if not tokens:
        return False
    rows = conn.execute(
        "SELECT id, title, content FROM nodes WHERE valid_until IS NULL"
    ).fetchall()
    scored: list[tuple[int, str]] = []
    for row in rows:
        blob = f"{row[1] or ''} {row[2] or ''}".lower()
        score = sum(1 for t in tokens if t in blob)
        if score:
            scored.append((score, row[0]))
    scored.sort(key=lambda x: (-x[0], x[1]))
    top = [nid for _, nid in scored[:k]]
    return _gold_hit(top, expected, k)


def _bm25_hit(conn, query: str, expected: list[str], k: int = 5) -> bool:
    """BM25/FTS-only baseline (no graph expansion / PPR)."""
    try:
        hits = fts_search_nodes(conn, query, limit=k)
    except Exception:
        return False
    ids = [nid for nid, _score in hits]
    return _gold_hit(ids, expected, k)


def run_cma_suite(
    _db_path: Path | None = None,
    *,
    fixture_path: Path | None = None,
) -> BenchSuiteResult:
    """Run CMA ability + token + latency + baseline scorecard."""
    del _db_path
    fixture = _load_fixture(fixture_path)
    floors = fixture.get("floors") or {}
    warm_n = int(fixture.get("latency_warm_repeats") or 5)
    set_skip_rolling_scores(True)
    conn, _db, project_dir = ephemeral_project_brain()
    cases: list[BenchCaseResult] = []
    ability_pass: dict[str, list[bool]] = defaultdict(list)
    hard_pass: list[bool] = []
    pack_tokens: list[int] = []
    recall_ms: list[float] = []
    pack_ms: list[float] = []
    brain_hits: list[bool] = []
    bm25_hits: list[bool] = []
    title_hits: list[bool] = []
    hard_brain: list[bool] = []
    hard_bm25: list[bool] = []

    try:
        _seed_corpus(conn, fixture)
        brain = BrainConfig()
        recall_default = RecallConfig()
        recall_rank = RecallConfig(abstain_on_low_confidence=False)
        fixture_id = str(fixture.get("id") or "cma")

        for query in fixture.get("queries", []):
            ability = str(query["ability"])
            qid = str(query["id"])
            mode = str(query.get("mode") or "recall")
            hard = bool(query.get("hard"))
            passed = False
            metric_ok = False
            detail = ""

            if ability == "abstention" or ability == "theme_leak" or query.get("should_recall") is False:
                t0 = time.perf_counter()
                result = recall_live(
                    conn,
                    query["query"],
                    limit=5,
                    recall=recall_default,
                    project_dir=project_dir,
                )
                recall_ms.append((time.perf_counter() - t0) * 1000.0)
                recalled = not result.abstained and bool(result.nodes)
                clean = result.abstained or not recalled
                if ability == "theme_leak" or query.get("report_only"):
                    # Measurement only: theme-adjacent leak rate (do not fail suite).
                    passed = True
                    metric_ok = clean
                    detail = (
                        f"leaked={int(recalled)} abstained={result.abstained} "
                        f"hits={len(result.nodes)}"
                    )
                else:
                    passed = clean
                    metric_ok = clean
                    detail = f"abstained={result.abstained} hits={len(result.nodes)}"

            elif mode == "traverse":
                t0 = time.perf_counter()
                traversal = traverse(
                    conn,
                    query["from_ref"],
                    max_hops=2,
                    direction="both",
                )
                elapsed = (time.perf_counter() - t0) * 1000.0
                recall_ms.append(elapsed)
                neighbors = traversal.nodes
                ok = True
                if "expect_min_neighbors" in query:
                    ok = len(neighbors) >= int(query["expect_min_neighbors"])
                if "expect_neighbor_substring" in query:
                    sub = str(query["expect_neighbor_substring"]).lower()
                    ok = ok and any(
                        sub in (n.title or "").lower() or sub in (n.path or "").lower()
                        for n in neighbors
                    )
                passed = ok
                metric_ok = ok
                detail = (
                    f"neighbors={len(neighbors)} resolved={traversal.resolved_id} "
                    f"ms={elapsed:.1f}"
                )

            else:
                k = int(query.get("k") or 5)
                expected = list(query.get("expected_node_ids") or [])
                prefer = list(query.get("prefer_node_ids") or [])
                forbidden = query.get("forbidden_top1")
                t0 = time.perf_counter()
                result = recall_live(
                    conn,
                    query["query"],
                    limit=k,
                    recall=recall_rank,
                    project_dir=project_dir,
                )
                recall_ms.append((time.perf_counter() - t0) * 1000.0)
                ids = [n.node_id for n in result.nodes]
                hit = _gold_hit(ids, expected, k) and not result.abstained
                if ability == "knowledge_update" and forbidden:
                    top = ids[0] if ids else None
                    hit = hit and top != forbidden
                if prefer and hit:
                    # Soft preference: prefer later-session fact in top-3 when listed.
                    if not _gold_hit(ids, prefer, min(3, k)):
                        detail_pref = "prefer_miss "
                    else:
                        detail_pref = "prefer_hit "
                else:
                    detail_pref = ""
                passed = hit
                metric_ok = hit
                detail = (
                    f"{detail_pref}top={ids[:3]} expected={expected} "
                    f"abstained={result.abstained}"
                )

                if query.get("baseline") and expected:
                    b_ok = _bm25_hit(conn, query["query"], expected, k)
                    t_ok = _title_scan_hit(conn, query["query"], expected, k)
                    brain_hits.append(hit)
                    bm25_hits.append(b_ok)
                    title_hits.append(t_ok)
                    detail += f" bm25={int(b_ok)} title={int(t_ok)}"
                    if query.get("hard_slice"):
                        hard_brain.append(hit)
                        hard_bm25.append(b_ok)
                        detail += " hard_slice=1"

                if query.get("measure_pack"):
                    t1 = time.perf_counter()
                    pack = compile_context_pack(
                        conn,
                        query["query"],
                        config=brain,
                        project_dir=project_dir,
                    )
                    pack_ms.append((time.perf_counter() - t1) * 1000.0)
                    used = int(pack.truncation.tokens_used)
                    pack_tokens.append(used)
                    detail += f" pack={used}/{pack.truncation.token_budget}"

            if mode != "traverse" and query.get("measure_pack") and warm_n > 0:
                for _ in range(warm_n):
                    t0 = time.perf_counter()
                    recall_live(
                        conn,
                        query["query"],
                        limit=5,
                        recall=recall_rank,
                        project_dir=project_dir,
                    )
                    recall_ms.append((time.perf_counter() - t0) * 1000.0)

            ability_pass[ability].append(metric_ok)
            if hard:
                hard_pass.append(metric_ok)
            cases.append(
                BenchCaseResult(
                    name=f"{ability}/{qid}",
                    passed=passed,
                    detail=detail,
                )
            )

        micro_vals = [p for vals in ability_pass.values() for p in vals]
        micro = (sum(1 for p in micro_vals if p) / len(micro_vals)) if micro_vals else 1.0
        hard_micro = (
            sum(1 for p in hard_pass if p) / len(hard_pass) if hard_pass else 1.0
        )
        mean_pack = statistics.mean(pack_tokens) if pack_tokens else 0.0
        r_p95 = _percentile(recall_ms, 95)
        p_p95 = _percentile(pack_ms, 95) if pack_ms else 0.0

        floor_micro = float(floors.get("ability_micro_avg", 0.70))
        floor_hard = float(floors.get("hard_micro_avg", 0.55))
        floor_pack = float(floors.get("mean_pack_tokens_max", 1500))
        floor_r = float(floors.get("recall_p95_ms", 800))
        floor_p = float(floors.get("pack_p95_ms", 1200))
        floor_lift = float(floors.get("baseline_lift_min", 0.0))

        brain_rate = (
            sum(1 for x in brain_hits if x) / len(brain_hits) if brain_hits else 0.0
        )
        bm25_rate = (
            sum(1 for x in bm25_hits if x) / len(bm25_hits) if bm25_hits else 0.0
        )
        title_rate = (
            sum(1 for x in title_hits if x) / len(title_hits) if title_hits else 0.0
        )
        lift_vs_bm25 = brain_rate - bm25_rate
        lift_vs_title = brain_rate - title_rate
        hard_brain_rate = (
            sum(1 for x in hard_brain if x) / len(hard_brain) if hard_brain else 0.0
        )
        hard_bm25_rate = (
            sum(1 for x in hard_bm25 if x) / len(hard_bm25) if hard_bm25 else 0.0
        )
        hard_lift = hard_brain_rate - hard_bm25_rate
        floor_hard_lift = float(floors.get("hard_slice_lift_min", 0.10))

        cases.append(
            BenchCaseResult(
                name="meta/fixture",
                passed=True,
                detail=f"{fixture_id} corpus_queries={len(fixture.get('queries', []))}",
            )
        )
        cases.append(
            BenchCaseResult(
                name="aggregate/ability_micro_avg",
                passed=micro >= floor_micro,
                detail=f"{micro:.3f} (floor>={floor_micro:.2f})",
            )
        )
        cases.append(
            BenchCaseResult(
                name="aggregate/hard_micro_avg",
                passed=hard_micro >= floor_hard,
                detail=f"{hard_micro:.3f} (floor>={floor_hard:.2f}, n={len(hard_pass)})",
            )
        )
        cases.append(
            BenchCaseResult(
                name="aggregate/mean_pack_tokens",
                passed=mean_pack <= floor_pack,
                detail=f"{mean_pack:.0f} (max<={floor_pack:.0f}, n={len(pack_tokens)})",
            )
        )
        cases.append(
            BenchCaseResult(
                name="aggregate/recall_p95_ms",
                passed=r_p95 <= floor_r,
                detail=f"{r_p95:.1f}ms (target<={floor_r:.0f})",
            )
        )
        cases.append(
            BenchCaseResult(
                name="aggregate/pack_p95_ms",
                passed=(not pack_ms) or p_p95 <= floor_p,
                detail=f"{p_p95:.1f}ms (target<={floor_p:.0f})",
            )
        )
        cases.append(
            BenchCaseResult(
                name="baseline/brain_vs_bm25",
                passed=True,  # measurement row; lift may be ~0 on keyword-heavy fixtures
                detail=(
                    f"brain={brain_rate:.3f} bm25={bm25_rate:.3f} "
                    f"lift={lift_vs_bm25:+.3f} n={len(brain_hits)} "
                    f"(gate_lift>={floor_lift:+.2f} met={lift_vs_bm25 >= floor_lift})"
                ),
            )
        )
        cases.append(
            BenchCaseResult(
                name="baseline/brain_vs_title_scan",
                passed=True,
                detail=(
                    f"brain={brain_rate:.3f} title={title_rate:.3f} "
                    f"lift={lift_vs_title:+.3f} n={len(brain_hits)} "
                    f"(gate_lift>={floor_lift:+.2f} met={lift_vs_title >= floor_lift})"
                ),
            )
        )
        cases.append(
            BenchCaseResult(
                name="baseline/hard_slice_brain_vs_bm25",
                passed=(not hard_brain) or hard_lift >= floor_hard_lift,
                detail=(
                    f"brain={hard_brain_rate:.3f} bm25={hard_bm25_rate:.3f} "
                    f"lift={hard_lift:+.3f} n={len(hard_brain)} "
                    f"(floor>={floor_hard_lift:.2f})"
                ),
            )
        )

        for ability, vals in sorted(ability_pass.items()):
            rate = sum(1 for p in vals if p) / len(vals) if vals else 1.0
            ab_floor = (
                floor_hard
                if ability in {"multi_session", "theme_leak"}
                else floor_micro
            )
            # theme_leak is reported; do not fail suite on ability rollup
            ab_passed = True if ability == "theme_leak" else rate >= ab_floor
            cases.append(
                BenchCaseResult(
                    name=f"ability/{ability}",
                    passed=ab_passed,
                    detail=f"{sum(1 for p in vals if p)}/{len(vals)} ({rate:.0%})",
                )
            )
    finally:
        cleanup_ephemeral_project(project_dir, conn)
        set_skip_rolling_scores(False)

    return BenchSuiteResult(
        suite="cma",
        passed=sum(1 for c in cases if c.passed),
        total=len(cases),
        cases=cases,
    )


def format_cma_summary(result: BenchSuiteResult) -> str:
    """Compact CMA headline for CLI / dated scorecards."""
    by_ability: dict[str, str] = {}
    micro = hard = mean_pack = recall_p95 = pack_p95 = bm25 = title = hard_lift = fixture = ""
    for case in result.cases:
        if case.name.startswith("ability/"):
            parts = case.detail.split()
            by_ability[case.name.removeprefix("ability/")] = parts[0] if parts else "?"
        elif case.name == "aggregate/ability_micro_avg":
            micro = case.detail
        elif case.name == "aggregate/hard_micro_avg":
            hard = case.detail
        elif case.name == "aggregate/mean_pack_tokens":
            mean_pack = case.detail
        elif case.name == "aggregate/recall_p95_ms":
            recall_p95 = case.detail
        elif case.name == "aggregate/pack_p95_ms":
            pack_p95 = case.detail
        elif case.name == "baseline/brain_vs_bm25":
            bm25 = case.detail
        elif case.name == "baseline/brain_vs_title_scan":
            title = case.detail
        elif case.name == "baseline/hard_slice_brain_vs_bm25":
            hard_lift = case.detail
        elif case.name == "meta/fixture":
            fixture = case.detail

    ability_bits = " ".join(f"{k}={v}" for k, v in sorted(by_ability.items()))
    lines = [
        f"CMA {result.passed}/{result.total} fixture={fixture}",
        f"  micro={micro} hard={hard}",
        f"  pack={mean_pack} recall_p95={recall_p95} pack_p95={pack_p95}",
        f"  baselines: {bm25} | {title}",
        f"  hard_slice_lift: {hard_lift}",
        f"  abilities: {ability_bits}",
    ]
    return "\n".join(lines)


def render_cma_scorecard_markdown(
    result: BenchSuiteResult,
    *,
    version: str,
    commit: str | None = None,
    machine: str | None = None,
    semantic: bool = False,
    command: str = "brainkm bench run cma",
) -> str:
    """Render a dated publishable scorecard markdown document."""
    lines = [
        "# Common Memory Axes (CMA) scorecard",
        "",
        f"- **brainkm version:** {version}",
        f"- **commit:** {commit or 'unknown'}",
        f"- **machine:** {machine or 'unknown'}",
        f"- **semantic embeddings:** {'on' if semantic else 'off (FTS+graph default)'}",
        f"- **command:** `{command}`",
        f"- **suite:** `{result.passed}/{result.total}` ({result.pass_rate:.0%})",
        "",
        "## Headline",
        "",
        "```",
        format_cma_summary(result),
        "```",
        "",
        "## Cases",
        "",
        "| Status | Case | Detail |",
        "|--------|------|--------|",
    ]
    for case in result.cases:
        status = "PASS" if case.passed else "FAIL"
        detail = case.detail.replace("|", "\\|")
        lines.append(f"| {status} | `{case.name}` | {detail} |")
    lines.extend(
        [
            "",
            "## Methodology notes",
            "",
            "- CMA maps LongMemEval *ability language* onto a **coding-agent project brain**",
            "  corpus (neurons + code graph + procedures), not chat-session haystacks.",
            "- Accuracy is always paired with **mean pack tokens (≤1500)** and **latency p95**.",
            "- Baselines: **BM25/FTS-only** and naive **title/content token scan** on the same gold.",
            "- Hard subset includes paraphrase, multi-session, and theme-adjacent abstention.",
            "- This is **not** a LongMemEval-S leaderboard claim. See BENCHMARKS.md.",
            "",
        ]
    )
    return "\n".join(lines)
