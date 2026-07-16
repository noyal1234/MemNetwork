"""Retrieval ranking bench — Recall@k / MRR / nDCG on held-out gold corpus."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from brainkm.bench.results import BenchCaseResult, BenchSuiteResult
from brainkm.config import set_skip_rolling_scores
from brainkm.models.brain_config import RecallConfig
from brainkm.services.bench_db import (
    cleanup_ephemeral_project,
    ensure_fixture_neuron,
    ephemeral_project_brain,
)
from brainkm.services.ir_metrics import (
    binary_relevance_grades,
    mrr,
    ndcg_at_k,
    recall_at_k,
)
from brainkm.services.recall import recall_live

DEFAULT_RETRIEVAL_FIXTURE_ID = "retrieval_v1"


@dataclass(frozen=True)
class RetrievalQuery:
    id: str
    query: str
    relevant_ids: tuple[str, ...]
    should_abstain: bool
    expect_noise_only: bool
    relevance: dict[str, float]


@dataclass(frozen=True)
class RetrievalCorpusNode:
    id: str
    kind: str
    subtype: str | None
    title: str
    content: str


@dataclass(frozen=True)
class RetrievalFixture:
    version: int
    id: str
    floors: dict[str, float]
    corpus: list[RetrievalCorpusNode]
    queries: list[RetrievalQuery]


def default_retrieval_fixture_path(fixture_id: str = DEFAULT_RETRIEVAL_FIXTURE_ID) -> Path:
    return Path(__file__).resolve().parents[1] / "bench" / "fixtures" / f"{fixture_id}.json"


def load_retrieval_fixture(path: Path | None = None) -> RetrievalFixture:
    if path is None:
        path = default_retrieval_fixture_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    corpus = [
        RetrievalCorpusNode(
            id=node["id"],
            kind=node.get("kind", "memory"),
            subtype=node.get("subtype"),
            title=node.get("title", ""),
            content=node.get("content", ""),
        )
        for node in data["corpus"]
    ]
    queries = [
        RetrievalQuery(
            id=item["id"],
            query=item["query"],
            relevant_ids=tuple(item.get("relevant_ids", [])),
            should_abstain=bool(item.get("should_abstain", False)),
            expect_noise_only=bool(item.get("expect_noise_only", False)),
            relevance={
                str(k): float(v) for k, v in (item.get("relevance") or {}).items()
            },
        )
        for item in data["queries"]
    ]
    floors = {str(k): float(v) for k, v in (data.get("floors") or {}).items()}
    return RetrievalFixture(
        version=int(data["version"]),
        id=data["id"],
        floors=floors,
        corpus=corpus,
        queries=queries,
    )


def load_package_retrieval_fixture(
    fixture_id: str = DEFAULT_RETRIEVAL_FIXTURE_ID,
) -> RetrievalFixture:
    package_path = resources.files("brainkm.bench.fixtures") / f"{fixture_id}.json"
    return load_retrieval_fixture(Path(str(package_path)))


def run_retrieval_suite(_db_path: Path) -> BenchSuiteResult:
    """Score ranking metrics on an isolated ephemeral gold corpus."""
    del _db_path
    fixture = load_package_retrieval_fixture()
    set_skip_rolling_scores(True)
    conn, _db, project_dir = ephemeral_project_brain()
    try:
        for node in fixture.corpus:
            ensure_fixture_neuron(
                conn,
                node_id=node.id,
                title=node.title,
                content=node.content,
                kind=node.kind,
                subtype=node.subtype,
            )
        conn.commit()

        recall_rank = RecallConfig(abstain_on_low_confidence=False)
        recall_abs = RecallConfig(abstain_on_low_confidence=True)
        ranking_r1: list[float] = []
        ranking_r5: list[float] = []
        ranking_mrr: list[float] = []
        ranking_ndcg: list[float] = []
        abstain_correct = 0
        abstain_total = 0
        theme_leak_correct = 0
        theme_leak_total = 0
        theme_ids = {
            node.id for node in fixture.corpus if not node.id.startswith("rb_noise_")
        }

        for item in fixture.queries:
            if item.expect_noise_only:
                theme_leak_total += 1
                result = recall_live(
                    conn,
                    item.query,
                    recall=recall_rank,
                    project_dir=project_dir,
                )
                ranked = [node.node_id for node in result.nodes]
                leaked = [doc_id for doc_id in ranked[:5] if doc_id in theme_ids]
                if not leaked:
                    theme_leak_correct += 1
                continue

            if item.should_abstain:
                abstain_total += 1
                result = recall_live(
                    conn,
                    item.query,
                    recall=recall_abs,
                    project_dir=project_dir,
                )
                if result.abstained or len(result.nodes) == 0:
                    abstain_correct += 1
                continue

            result = recall_live(
                conn,
                item.query,
                recall=recall_rank,
                project_dir=project_dir,
            )
            ranked = [node.node_id for node in result.nodes]
            grades = item.relevance or binary_relevance_grades(item.relevant_ids)
            ranking_r1.append(recall_at_k(ranked, item.relevant_ids, k=1))
            ranking_r5.append(recall_at_k(ranked, item.relevant_ids, k=5))
            ranking_mrr.append(mrr(ranked, item.relevant_ids))
            ranking_ndcg.append(ndcg_at_k(ranked, grades, k=5))
    finally:
        cleanup_ephemeral_project(project_dir, conn)
        set_skip_rolling_scores(False)

    def _mean(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    mean_r1 = _mean(ranking_r1)
    mean_r5 = _mean(ranking_r5)
    mean_mrr = _mean(ranking_mrr)
    mean_ndcg = _mean(ranking_ndcg)
    abstain_acc = (abstain_correct / abstain_total) if abstain_total else 1.0
    theme_leak_acc = (
        (theme_leak_correct / theme_leak_total) if theme_leak_total else 1.0
    )

    floors = fixture.floors
    cases = [
        BenchCaseResult(
            name="recall_at_1",
            passed=mean_r1 >= floors.get("recall_at_1", 0.4),
            detail=f"{mean_r1:.3f} (floor>={floors.get('recall_at_1', 0.4):.2f}, n={len(ranking_r1)})",
        ),
        BenchCaseResult(
            name="recall_at_5",
            passed=mean_r5 >= floors.get("recall_at_5", 0.55),
            detail=f"{mean_r5:.3f} (floor>={floors.get('recall_at_5', 0.55):.2f}, n={len(ranking_r5)})",
        ),
        BenchCaseResult(
            name="mrr",
            passed=mean_mrr >= floors.get("mrr", 0.45),
            detail=f"{mean_mrr:.3f} (floor>={floors.get('mrr', 0.45):.2f})",
        ),
        BenchCaseResult(
            name="ndcg_at_5",
            passed=mean_ndcg >= floors.get("ndcg_at_5", 0.5),
            detail=f"{mean_ndcg:.3f} (floor>={floors.get('ndcg_at_5', 0.5):.2f})",
        ),
        BenchCaseResult(
            name="theme_leak_accuracy",
            passed=theme_leak_acc >= floors.get("theme_leak_accuracy", 0.9),
            detail=(
                f"{theme_leak_acc:.3f} (floor>={floors.get('theme_leak_accuracy', 0.9):.2f}, "
                f"{theme_leak_correct}/{theme_leak_total})"
            ),
        ),
        BenchCaseResult(
            name="abstain_accuracy",
            passed=abstain_acc >= floors.get("abstain_accuracy", 0.85),
            detail=(
                f"{abstain_acc:.3f} (floor>={floors.get('abstain_accuracy', 0.85):.2f}, "
                f"{abstain_correct}/{abstain_total})"
            ),
        ),
        BenchCaseResult(
            name="fixture_scale",
            passed=len(fixture.queries) >= 60 and len(fixture.corpus) >= 30,
            detail=f"queries={len(fixture.queries)} corpus={len(fixture.corpus)}",
        ),
    ]
    passed = sum(1 for case in cases if case.passed)
    return BenchSuiteResult(suite="retrieval", passed=passed, total=len(cases), cases=cases)
