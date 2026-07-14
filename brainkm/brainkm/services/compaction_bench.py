"""Compaction-fidelity bench suite implementation."""

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
    return Path(__file__).resolve().parents[1] / "bench" / "fixtures" / "compaction_v1.json"


def _fidelity(key_facts: list[str], recall_text: str) -> float:
    if not key_facts:
        return 1.0
    hits = sum(1 for fact in key_facts if fact.lower() in recall_text.lower())
    return hits / len(key_facts)


def run_compaction_suite(db_path: Path) -> BenchSuiteResult:
    """Run compaction fidelity checks on an isolated ephemeral brain."""
    del db_path
    fixture = json.loads(_fixture_path().read_text(encoding="utf-8"))
    set_skip_rolling_scores(True)
    conn, _db, project_dir = ephemeral_project_brain()
    cases: list[BenchCaseResult] = []
    try:
        for cycle in fixture["cycles"]:
            for node in cycle["neurons"]:
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
                cycle["query"],
                recall=RecallConfig(abstain_on_low_confidence=False),
                project_dir=project_dir,
            )
            recall_text = "\n".join(ranked.node_id for ranked in result.nodes)
            for ranked in result.nodes:
                row = conn.execute(
                    "SELECT title, content FROM nodes WHERE id = ?",
                    (ranked.node_id,),
                ).fetchone()
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
        cleanup_ephemeral_project(project_dir, conn)
        set_skip_rolling_scores(False)
    return BenchSuiteResult(
        suite="compaction",
        passed=sum(1 for case in cases if case.passed),
        total=len(cases),
        cases=cases,
    )
