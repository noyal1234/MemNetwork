"""LongMemEval-lite bench suite implementation."""

from __future__ import annotations

import json
from pathlib import Path

from brainkm.bench.results import BenchCaseResult, BenchSuiteResult
from brainkm.config import set_skip_rolling_scores
from brainkm.models.brain_config import RecallConfig
from brainkm.services.bench_db import (
    cleanup_ephemeral_project,
    ensure_fixture_neuron,
    ephemeral_project_brain,
)
from brainkm.services.recall import recall_live


def _fixture_path() -> Path:
    return Path(__file__).resolve().parents[1] / "bench" / "fixtures" / "longmem_v1.json"


def run_longmem_suite(db_path: Path) -> BenchSuiteResult:
    """Run LongMemEval-lite queries on an isolated ephemeral brain."""
    del db_path
    fixture = json.loads(_fixture_path().read_text(encoding="utf-8"))
    set_skip_rolling_scores(True)
    conn, _db, project_dir = ephemeral_project_brain()
    cases: list[BenchCaseResult] = []
    try:
        for node in fixture["corpus"]:
            ensure_fixture_neuron(
                conn,
                node_id=node["id"],
                title=node["title"],
                content=node["content"],
                kind=node.get("kind", "memory"),
                subtype=node.get("subtype"),
            )
        conn.commit()

        for query in fixture["queries"]:
            result = recall_live(
                conn,
                query["query"],
                recall=RecallConfig(abstain_on_low_confidence=False),
                project_dir=project_dir,
            )
            top = result.nodes[0].node_id if result.nodes else None
            recalled = not result.abstained and top is not None
            if query["should_recall"]:
                passed = recalled and top == query["expected_node_id"]
            else:
                passed = result.abstained or not recalled
            cases.append(
                BenchCaseResult(
                    name=query["id"],
                    passed=passed,
                    detail=(
                        f"ability={query['ability']} top={top} "
                        f"expected={query['expected_node_id']} abstained={result.abstained}"
                    ),
                )
            )
    finally:
        cleanup_ephemeral_project(project_dir, conn)
        set_skip_rolling_scores(False)
    return BenchSuiteResult(
        suite="longmem",
        passed=sum(1 for case in cases if case.passed),
        total=len(cases),
        cases=cases,
    )
