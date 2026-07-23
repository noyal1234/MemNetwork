"""Staleness / contradiction bench — superseded facts must not win or leak into packs."""

from __future__ import annotations

import json
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
from brainkm.services.memory import supersede_neuron
from brainkm.services.recall import recall_live


def load_staleness_fixture(fixture_id: str = "staleness_v1") -> dict:
    path = resources.files("brainkm.bench.fixtures").joinpath(f"{fixture_id}.json")
    return json.loads(path.read_text(encoding="utf-8"))


def run_staleness_suite(_db_path: Path | None = None) -> BenchSuiteResult:
    del _db_path
    fixture = load_staleness_fixture()
    floors = fixture.get("floors") or {}
    set_skip_rolling_scores(True)
    conn, _db, project = ephemeral_project_brain()
    cases: list[BenchCaseResult] = []
    top1_ok = 0
    top1_total = 0
    pack_ok = 0
    pack_total = 0
    try:
        for node in fixture.get("corpus", []):
            ensure_fixture_neuron(
                conn,
                node_id=node["id"],
                title=node["title"],
                content=node.get("content"),
                kind=node.get("kind") or "memory",
                subtype=node.get("subtype") or "fact",
            )
        for pair in fixture.get("supersedes") or []:
            if len(pair) != 2:
                continue
            new_id, old_id = pair
            row = conn.execute("SELECT valid_until FROM nodes WHERE id = ?", (old_id,)).fetchone()
            if row is not None and row[0] is None:
                supersede_neuron(conn, old_id, replacement_id=new_id)
        conn.commit()

        recall_cfg = RecallConfig(abstain_on_low_confidence=False)
        cfg = BrainConfig(recall=recall_cfg)
        for query in fixture.get("queries", []):
            qid = str(query["id"])
            result = recall_live(
                conn,
                query["query"],
                limit=5,
                recall=recall_cfg,
                project_dir=project,
            )
            ids = [n.node_id for n in result.nodes]
            top = ids[0] if ids else None
            expected = query.get("expected_top")
            forbidden = query.get("forbidden_top")
            top1_total += 1
            # Top must be the replacement; superseded (archived) must not appear.
            ok = top == expected and (forbidden is None or forbidden not in ids)
            if ok:
                top1_ok += 1
            cases.append(
                BenchCaseResult(
                    name=f"top1/{qid}",
                    passed=ok,
                    detail=f"top={top} expected={expected} forbidden={forbidden}",
                )
            )

            if query.get("measure_pack"):
                pack_total += 1
                pack = compile_context_pack(
                    conn,
                    query["query"],
                    config=cfg,
                    project_dir=project,
                )
                text = (pack.pack_text or "").lower()
                stale_hits = [
                    s for s in query.get("stale_body_substrings") or [] if str(s).lower() in text
                ]
                clean = not stale_hits
                if clean:
                    pack_ok += 1
                cases.append(
                    BenchCaseResult(
                        name=f"pack/{qid}",
                        passed=clean,
                        detail=(
                            f"stale_hits={stale_hits!r} tokens={getattr(pack, 'total_tokens', '?')}"
                        ),
                    )
                )
    finally:
        cleanup_ephemeral_project(project, conn)
        set_skip_rolling_scores(False)

    top1_rate = top1_ok / top1_total if top1_total else 1.0
    pack_rate = pack_ok / pack_total if pack_total else 1.0
    cases.insert(
        0,
        BenchCaseResult(
            name="aggregate/supersede_top1",
            passed=top1_rate >= float(floors.get("supersede_top1", 0.8)),
            detail=f"{top1_rate:.3f} ({top1_ok}/{top1_total})",
        ),
    )
    cases.insert(
        1,
        BenchCaseResult(
            name="aggregate/stale_injection_clean",
            passed=pack_rate >= float(floors.get("stale_injection_clean", 0.8)),
            detail=f"{pack_rate:.3f} ({pack_ok}/{pack_total})",
        ),
    )
    passed = sum(1 for c in cases if c.passed)
    return BenchSuiteResult(
        suite="staleness",
        passed=passed,
        total=len(cases),
        cases=cases,
    )


def format_staleness_summary(result: BenchSuiteResult) -> str:
    top1 = next((c.detail for c in result.cases if c.name == "aggregate/supersede_top1"), "?")
    pack = next(
        (c.detail for c in result.cases if c.name == "aggregate/stale_injection_clean"),
        "n/a",
    )
    return f"Staleness: supersede_top1={top1} stale_injection_clean={pack}"
