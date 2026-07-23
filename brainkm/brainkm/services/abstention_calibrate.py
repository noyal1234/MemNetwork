"""Calibrate recall abstention thresholds from bench fixtures."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

from brainkm.db.connection import connect
from brainkm.db.migrate import migrate
from brainkm.db.paths import brain_dir
from brainkm.logging_config import get_logger
from brainkm.models.abstention_calibration import AbstentionCalibration
from brainkm.models.brain_config import RecallConfig
from brainkm.services.abstention import (
    best_bm25_score,
    corpus_bm25_percentile,
    should_abstain,
)
from brainkm.services.search import fts_search_nodes

logger = get_logger("services.abstention_calibrate")

CALIBRATION_FILENAME = "abstention_calibration.json"
DEFAULT_FIXTURE_ID = "abstention_v1"


class CalibrationError(RuntimeError):
    """Fixture queries cannot be satisfied with any percentile threshold."""


@dataclass(frozen=True)
class FixtureNode:
    id: str
    kind: str
    subtype: str | None
    title: str
    content: str


@dataclass(frozen=True)
class FixtureQuery:
    query: str
    should_recall: bool
    expected_node_id: str | None = None


@dataclass(frozen=True)
class AbstentionFixture:
    version: int
    id: str
    corpus: list[FixtureNode]
    queries: list[FixtureQuery]


@dataclass(frozen=True)
class QueryEval:
    query: str
    should_recall: bool
    abstained: bool
    best_score: float | None
    top_node_id: str | None
    passed: bool


def calibration_path(project_dir: Path | None = None) -> Path:
    return brain_dir(project_dir) / CALIBRATION_FILENAME


def default_fixture_path(fixture_id: str = DEFAULT_FIXTURE_ID) -> Path:
    return Path(__file__).resolve().parents[1] / "bench" / "fixtures" / f"{fixture_id}.json"


def load_abstention_fixture(path: Path | None = None) -> AbstentionFixture:
    """Load a bench abstention fixture from disk or package defaults."""
    if path is None:
        path = default_fixture_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    corpus = [
        FixtureNode(
            id=item["id"],
            kind=item.get("kind", "memory"),
            subtype=item.get("subtype"),
            title=item.get("title", ""),
            content=item.get("content", ""),
        )
        for item in data["corpus"]
    ]
    queries = [
        FixtureQuery(
            query=item["query"],
            should_recall=item["should_recall"],
            expected_node_id=item.get("expected_node_id"),
        )
        for item in data["queries"]
    ]
    return AbstentionFixture(
        version=int(data.get("version", 1)),
        id=str(data.get("id", path.stem)),
        corpus=corpus,
        queries=queries,
    )


def load_package_fixture(fixture_id: str = DEFAULT_FIXTURE_ID) -> AbstentionFixture:
    """Load a packaged bench fixture via importlib resources."""
    package_path = resources.files("brainkm.bench.fixtures") / f"{fixture_id}.json"
    return load_abstention_fixture(Path(str(package_path)))


def seed_fixture_corpus(conn: sqlite3.Connection, fixture: AbstentionFixture) -> None:
    """Insert fixture neurons when absent (idempotent by node id)."""
    now = datetime.now(UTC).isoformat()
    for node in fixture.corpus:
        exists = conn.execute(
            "SELECT 1 FROM nodes WHERE id = ?",
            (node.id,),
        ).fetchone()
        if exists:
            continue
        conn.execute(
            """
            INSERT INTO nodes (
              id, kind, subtype, title, content, ingested_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node.id,
                node.kind,
                node.subtype,
                node.title,
                node.content,
                now,
                now,
                now,
            ),
        )


def _evaluate_query(
    conn: sqlite3.Connection,
    item: FixtureQuery,
    *,
    corpus_threshold: float,
) -> QueryEval:
    hits = fts_search_nodes(conn, item.query, limit=5)
    seed_scores = [score for _, score in hits]
    abstained = should_abstain(
        seed_scores,
        RecallConfig(abstain_mode="percentile"),
        corpus_threshold=corpus_threshold,
    )
    best = best_bm25_score(seed_scores)
    top_node_id = hits[0][0] if hits else None
    passed = abstained != item.should_recall
    if item.should_recall and item.expected_node_id and top_node_id:
        passed = passed and top_node_id == item.expected_node_id
    return QueryEval(
        query=item.query,
        should_recall=item.should_recall,
        abstained=abstained,
        best_score=best,
        top_node_id=top_node_id,
        passed=passed,
    )


def evaluate_fixture_queries(
    conn: sqlite3.Connection,
    fixture: AbstentionFixture,
    *,
    corpus_threshold: float,
) -> list[QueryEval]:
    return [
        _evaluate_query(conn, item, corpus_threshold=corpus_threshold) for item in fixture.queries
    ]


def _queries_pass(conn: sqlite3.Connection, fixture: AbstentionFixture, threshold: float) -> bool:
    return all(
        item.passed for item in evaluate_fixture_queries(conn, fixture, corpus_threshold=threshold)
    )


def find_percentile_threshold(
    conn: sqlite3.Connection,
    fixture: AbstentionFixture,
    recall: RecallConfig,
) -> tuple[float, float]:
    """Find a percentile whose corpus threshold satisfies all fixture queries."""
    candidates = sorted({recall.abstain_percentile, *[p / 100 for p in range(5, 96, 5)]})
    for percentile in candidates:
        threshold = corpus_bm25_percentile(conn, percentile)
        if threshold is None:
            continue
        if _queries_pass(conn, fixture, threshold):
            if percentile != recall.abstain_percentile:
                logger.warning(
                    "Adjusted abstain_percentile from %s to %s for fixture %s",
                    recall.abstain_percentile,
                    percentile,
                    fixture.id,
                )
            return percentile, threshold

    msg = f"No percentile threshold satisfies fixture {fixture.id}"
    raise CalibrationError(msg)


def calibrate_min_recall_score(
    conn: sqlite3.Connection,
    fixture: AbstentionFixture,
) -> float | None:
    """Derive an absolute min_recall_score from labeled fixture query scores."""
    positive_abs: list[float] = []
    negative_abs: list[float] = []

    for item in fixture.queries:
        hits = fts_search_nodes(conn, item.query, limit=5)
        best = best_bm25_score([score for _, score in hits])
        if best is None:
            continue
        magnitude = abs(best)
        if item.should_recall:
            positive_abs.append(magnitude)
        else:
            negative_abs.append(magnitude)

    if not positive_abs:
        return None
    if not negative_abs:
        return min(positive_abs) * 0.75

    upper = min(positive_abs)
    lower = max(negative_abs)
    if upper <= lower:
        return upper * 0.9
    return lower + (upper - lower) * 0.5


def calibrate_abstention(
    conn: sqlite3.Connection,
    recall: RecallConfig,
    fixture: AbstentionFixture,
    *,
    seed_corpus: bool = True,
) -> AbstentionCalibration:
    """Compute percentile and absolute thresholds validated against fixture queries."""
    if seed_corpus:
        seed_fixture_corpus(conn, fixture)
        conn.commit()

    percentile, threshold = find_percentile_threshold(conn, fixture, recall)
    evaluations = evaluate_fixture_queries(conn, fixture, corpus_threshold=threshold)
    min_score = calibrate_min_recall_score(conn, fixture)

    return AbstentionCalibration(
        fixture_id=fixture.id,
        abstain_percentile=percentile,
        corpus_bm25_threshold=threshold,
        min_recall_score=min_score,
        query_pass_count=sum(1 for item in evaluations if item.passed),
        query_total=len(evaluations),
        calibrated_at=datetime.now(UTC).isoformat(),
    )


def save_calibration(
    calibration: AbstentionCalibration,
    project_dir: Path | None = None,
) -> Path:
    path = calibration_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        calibration.model_dump_json(indent=2),
        encoding="utf-8",
    )
    logger.info(
        "saved abstention calibration fixture=%s percentile=%s threshold=%s",
        calibration.fixture_id,
        calibration.abstain_percentile,
        calibration.corpus_bm25_threshold,
    )
    return path


def load_calibration(project_dir: Path | None = None) -> AbstentionCalibration | None:
    path = calibration_path(project_dir)
    if not path.is_file():
        return None
    return AbstentionCalibration.model_validate_json(path.read_text(encoding="utf-8"))


ROLLING_SCORES_FILENAME = "abstention_rolling_scores.json"
ROLLING_WINDOW = 200


def rolling_scores_path(project_dir: Path | None = None) -> Path:
    return brain_dir(project_dir) / ROLLING_SCORES_FILENAME


def record_rolling_score(score: float, project_dir: Path | None = None) -> None:
    path = rolling_scores_path(project_dir)
    scores: list[float] = []
    if path.is_file():
        scores = _load_rolling_scores(path)
    scores.append(float(score))
    scores = scores[-ROLLING_WINDOW:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scores), encoding="utf-8")


def _load_rolling_scores(path: Path) -> list[float]:
    """Load rolling BM25 scores, ignoring corrupt non-numeric entries."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return []
    cleaned: list[float] = []
    for item in raw:
        try:
            cleaned.append(float(item))
        except (TypeError, ValueError):
            continue
    return cleaned


def rolling_percentile_threshold(
    project_dir: Path | None,
    percentile: float,
) -> float | None:
    path = rolling_scores_path(project_dir)
    if not path.is_file():
        return None
    scores = _load_rolling_scores(path)
    if len(scores) < 10:
        return None
    import statistics

    quantiles = statistics.quantiles(scores, n=100, method="inclusive")
    index = max(0, min(len(quantiles) - 1, int(percentile * 100) - 1))
    return quantiles[index]


def calibrate_reference(project_dir: Path | None = None) -> AbstentionCalibration:
    """Calibrate from packaged fixture in a throwaway DB; persist to project .brain/."""
    fixture = load_package_fixture()
    db_path = brain_dir(project_dir) / ".calibration-tmp.db"
    migrate(db_path=db_path, run_integrity_check=False)
    conn = connect(db_path)
    try:
        calibration = calibrate_abstention(conn, RecallConfig(), fixture, seed_corpus=True)
        conn.commit()
    finally:
        conn.close()
        db_path.unlink(missing_ok=True)
        db_path.with_suffix(".db-wal").unlink(missing_ok=True)
        db_path.with_suffix(".db-shm").unlink(missing_ok=True)

    save_calibration(calibration, project_dir)
    return calibration


def calibrate_project(
    project_dir: Path | None = None,
    *,
    recall: RecallConfig | None = None,
    fixture_id: str = DEFAULT_FIXTURE_ID,
    seed_reference_corpus: bool = False,
) -> AbstentionCalibration:
    """Calibrate against live brain.db, optionally seeding reference corpus neurons."""
    from brainkm.db.paths import brain_db_path

    recall_cfg = recall or RecallConfig()
    fixture = load_package_fixture(fixture_id)
    db_path = brain_db_path(project_dir)
    migrate(db_path=db_path, run_integrity_check=False)
    conn = connect(db_path)
    try:
        calibration = calibrate_abstention(
            conn,
            recall_cfg,
            fixture,
            seed_corpus=seed_reference_corpus,
        )
        conn.commit()
    finally:
        conn.close()

    save_calibration(calibration, project_dir)
    return calibration


def recalibrate_after_repair(project_dir: Path | None = None) -> AbstentionCalibration | None:
    """Recalibrate abstention thresholds after FTS repair."""
    try:
        return calibrate_project(project_dir=project_dir, seed_reference_corpus=False)
    except CalibrationError:
        return None
