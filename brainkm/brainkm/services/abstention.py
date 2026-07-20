"""Recall abstention helpers for BM25 score thresholds."""

from __future__ import annotations

import sqlite3
import statistics
from pathlib import Path

from brainkm.models.brain_config import RecallConfig

# SQLite FTS5 bm25() returns negative values; lower (more negative) is a better match.
CorpusBroadQuery = "memory OR decision OR rule OR fact OR code OR error"

# Below this active-node count, BM25 magnitudes are too small for the absolute
# min_bm25_strength floor — skip it so fresh brains still recall (percentile mode
# and CMA benches remain unaffected once the corpus grows).
SMALL_CORPUS_THRESHOLD = 20


def best_bm25_score(scores: list[float]) -> float | None:
    """Return the strongest BM25 score from a result set."""
    if not scores:
        return None
    return min(scores)


def active_corpus_size(conn: sqlite3.Connection) -> int:
    """Count active (non-archived) nodes used for retrieval."""
    row = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE valid_until IS NULL"
    ).fetchone()
    return int(row[0]) if row else 0


def corpus_bm25_percentile(
    conn: sqlite3.Connection,
    percentile: float,
    *,
    broad_query: str = CorpusBroadQuery,
    sample_limit: int = 200,
) -> float | None:
    """Estimate a corpus BM25 percentile using a broad FTS sample."""
    rows = conn.execute(
        """
        SELECT bm25(nodes_fts) AS score
        FROM nodes_fts
        JOIN nodes n ON n.rowid = nodes_fts.rowid
        WHERE nodes_fts MATCH ?
          AND n.valid_until IS NULL
        ORDER BY score
        LIMIT ?
        """,
        (broad_query, sample_limit),
    ).fetchall()
    if not rows:
        return None

    scores = [float(row[0]) for row in rows]
    if len(scores) == 1:
        return scores[0]

    quantiles = statistics.quantiles(scores, n=100, method="inclusive")
    index = max(0, min(len(quantiles) - 1, int(percentile * 100) - 1))
    return quantiles[index]


def should_abstain(
    seed_scores: list[float],
    recall: RecallConfig,
    *,
    corpus_threshold: float | None = None,
    active_nodes: int | None = None,
) -> bool:
    """Return True when recall should return no neurons."""
    if not recall.abstain_on_low_confidence:
        return False

    best = best_bm25_score(seed_scores)
    if best is None:
        return True

    # Absolute strength floor is unreliable on tiny corpora (BM25 magnitudes stay low).
    apply_floor = active_nodes is None or active_nodes >= SMALL_CORPUS_THRESHOLD
    if (
        apply_floor
        and recall.min_bm25_strength is not None
        and abs(best) < recall.min_bm25_strength
    ):
        return True

    if recall.abstain_mode == "absolute":
        threshold = recall.min_recall_score
        if threshold is None:
            return False
        return abs(best) < threshold

    if corpus_threshold is None:
        # Fresh / empty corpus: fall back to absolute min_recall_score when set.
        threshold = recall.min_recall_score
        if threshold is None:
            return False
        return abs(best) < threshold

    # Weaker matches sit closer to zero; abstain when best score is above the P-threshold.
    return best > corpus_threshold


def resolve_corpus_threshold(
    conn: sqlite3.Connection,
    recall: RecallConfig,
    *,
    project_dir: Path | None = None,
) -> float | None:
    """Return the BM25 corpus threshold for percentile abstention.

    Prefer the *least strict* (highest / closest-to-zero) among live corpus,
    rolling, and calibration thresholds so a polluted rolling window cannot
    block all recalls.
    """
    if not recall.abstain_on_low_confidence or recall.abstain_mode != "percentile":
        return None

    from brainkm.services.abstention_calibrate import (
        load_calibration,
        rolling_percentile_threshold,
    )

    candidates: list[float] = []
    live = corpus_bm25_percentile(conn, recall.abstain_percentile)
    if live is not None:
        candidates.append(live)

    rolling = rolling_percentile_threshold(project_dir, recall.abstain_percentile)
    if rolling is not None:
        candidates.append(rolling)

    calibration = load_calibration(project_dir)
    if calibration and calibration.corpus_bm25_threshold is not None:
        candidates.append(float(calibration.corpus_bm25_threshold))

    if not candidates:
        return None
    return max(candidates)


def record_query_score(
    seed_scores: list[float],
    *,
    project_dir: Path | None = None,
) -> None:
    """Append best BM25 score to rolling window for V1.5 abstention drift tracking."""
    from brainkm.config import get_settings

    if get_settings().brainkm_skip_rolling_scores:
        return
    from brainkm.services.abstention_calibrate import record_rolling_score

    best = best_bm25_score(seed_scores)
    if best is not None:
        record_rolling_score(best, project_dir)


def should_abstain_for_query(
    conn: sqlite3.Connection,
    seed_scores: list[float],
    recall: RecallConfig,
    *,
    project_dir: Path | None = None,
) -> bool:
    """Evaluate abstention for a query, using bench calibration when present."""
    from brainkm.logging_config import get_logger

    record_query_score(seed_scores, project_dir=project_dir)
    corpus_threshold = resolve_corpus_threshold(conn, recall, project_dir=project_dir)
    nodes = active_corpus_size(conn)
    abstain = should_abstain(
        seed_scores,
        recall,
        corpus_threshold=corpus_threshold,
        active_nodes=nodes,
    )
    best = best_bm25_score(seed_scores)
    get_logger("services.abstention").debug(
        "abstain=%s best=%s threshold=%s mode=%s percentile=%s active_nodes=%s",
        abstain,
        best,
        corpus_threshold,
        recall.abstain_mode,
        recall.abstain_percentile,
        nodes,
    )
    return abstain
