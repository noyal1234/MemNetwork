"""DMR bench suite implementation."""

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
    return Path(__file__).resolve().parents[1] / "bench" / "fixtures" / "dmr_v1.json"


def run_dmr_suite(db_path: Path) -> BenchSuiteResult:
    """Run DMR-lite scenarios on an isolated ephemeral brain (not the live DB).

    ``db_path`` is accepted for API compatibility with ``run_bench_suite`` / the TUI
    but fixture inserts never touch the project's live ``brain.db``.
    """
    del db_path  # fixture suite — always ephemeral
    fixture = json.loads(_fixture_path().read_text(encoding="utf-8"))
    set_skip_rolling_scores(True)
    conn, _db, project_dir = ephemeral_project_brain()
    cases: list[BenchCaseResult] = []
    try:
        for scenario in fixture["scenarios"]:
            for node in scenario["session_a_neurons"]:
                ensure_fixture_neuron(
                    conn,
                    node_id=node["id"],
                    title=node["title"],
                    content=node["content"],
                    kind=node.get("kind", "memory"),
                    subtype=node.get("subtype"),
                )
            conn.commit()
            result = recall_live(
                conn,
                scenario["query"],
                recall=RecallConfig(abstain_on_low_confidence=False),
                project_dir=project_dir,
            )
            top = result.nodes[0].node_id if result.nodes else None
            passed = not result.abstained and top == scenario["expected_node_id"]
            cases.append(
                BenchCaseResult(
                    name=scenario["id"],
                    passed=passed,
                    detail=(
                        f"recall@1={top} expected={scenario['expected_node_id']} "
                        f"abstained={result.abstained}"
                    ),
                )
            )
    finally:
        cleanup_ephemeral_project(project_dir, conn)
        set_skip_rolling_scores(False)
    return BenchSuiteResult(
        suite="dmr",
        passed=sum(1 for case in cases if case.passed),
        total=len(cases),
        cases=cases,
    )
