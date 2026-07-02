"""Compaction-fidelity bench suite implementation."""

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
    return Path(__file__).resolve().parents[1] / "bench" / "fixtures" / "compaction_v1.json"


def _fidelity(key_facts: list[str], recall_text: str) -> float:
    if not key_facts:
        return 1.0
    hits = sum(1 for fact in key_facts if fact.lower() in recall_text.lower())
    return hits / len(key_facts)


def run_compaction_suite(db_path: Path) -> BenchSuiteResult:
    fixture = json.loads(_fixture_path().read_text(encoding="utf-8"))
    migrate(db_path=db_path, run_integrity_check=False)
    conn = connect(db_path)
    cases: list[BenchCaseResult] = []
    try:
        for cycle in fixture["cycles"]:
            for node in cycle["neurons"]:
                create_neuron(
                    conn,
                    title=node["title"],
                    content=node["content"],
                    kind=node.get("kind", "memory"),
                    subtype=node.get("subtype"),
                    node_id=node["id"],
                )
            conn.commit()
            result = recall_live(
                conn,
                cycle["query"],
                recall=RecallConfig(),
                project_dir=db_path.parent.parent,
            )
            recall_text = "\n".join(f"{ranked.node_id}" for ranked in result.nodes)
            for ranked in result.nodes:
                row = conn.execute("SELECT title, content FROM nodes WHERE id = ?", (ranked.node_id,)).fetchone()
                if row is not None:
                    recall_text += f"\n{row['title']}\n{row['content'] or ''}"
            score = _fidelity(cycle["key_facts"], recall_text)
            passed = score >= float(cycle["fidelity_target"])
            cases.append(
                BenchCaseResult(
                    name=cycle["id"],
                    passed=passed,
                    detail=f"fidelity={score:.2f} target={cycle['fidelity_target']:.2f}",
                )
            )
    finally:
        conn.close()
    return BenchSuiteResult(
        suite="compaction",
        passed=sum(1 for case in cases if case.passed),
        total=len(cases),
        cases=cases,
    )

