"""LongMemEval-lite bench suite implementation."""

from __future__ import annotations

import json
from pathlib import Path

from brainkm.bench.results import BenchCaseResult, BenchSuiteResult
from brainkm.db.connection import connect
from brainkm.db.migrate import migrate
from brainkm.models.brain_config import RecallConfig
from brainkm.services.memory import create_neuron
from brainkm.services.recall import recall_live


def _fixture_path() -> Path:
    return Path(__file__).resolve().parents[1] / "bench" / "fixtures" / "longmem_v1.json"


def run_longmem_suite(db_path: Path) -> BenchSuiteResult:
    fixture = json.loads(_fixture_path().read_text(encoding="utf-8"))
    migrate(db_path=db_path, run_integrity_check=False)
    conn = connect(db_path)
    cases: list[BenchCaseResult] = []
    try:
        for node in fixture["corpus"]:
            create_neuron(
                conn,
                title=node["title"],
                content=node["content"],
                kind=node.get("kind", "memory"),
                subtype=node.get("subtype"),
                node_id=node["id"],
            )
        conn.commit()

        for query in fixture["queries"]:
            result = recall_live(
                conn,
                query["query"],
                recall=RecallConfig(),
                project_dir=db_path.parent.parent,
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
                        f"ability={query['ability']} top={top} expected={query['expected_node_id']} "
                        f"abstained={result.abstained}"
                    ),
                )
            )
    finally:
        conn.close()
    return BenchSuiteResult(
        suite="longmem",
        passed=sum(1 for case in cases if case.passed),
        total=len(cases),
        cases=cases,
    )

