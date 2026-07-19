"""Side-by-side retrieval adapters for head-to-head bench tables.

Arms:
- ``naive`` — title/content token overlap scan (grep-like baseline)
- ``bm25`` / ``brainkm`` — scored by callers using the same gold + metrics
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from brainkm.services.ir_metrics import mrr, precision_at_k, recall_at_k

_TOKEN_RE = re.compile(r"[a-z0-9_./-]{2,}", re.I)


def tokenize(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "")}


def naive_title_scan_rank(
    query: str,
    titles: Mapping[str, str],
    contents: Mapping[str, str],
    *,
    limit: int = 10,
) -> list[str]:
    """Rank node ids by overlap of query tokens with title+content (no FTS)."""
    q_tokens = tokenize(query)
    if not q_tokens:
        return []
    scored: list[tuple[str, float]] = []
    for node_id, title in titles.items():
        blob = f"{title}\n{contents.get(node_id, '')}"
        doc_tokens = tokenize(blob)
        if not doc_tokens:
            continue
        overlap = len(q_tokens & doc_tokens)
        if overlap <= 0:
            continue
        # Prefer denser title hits slightly.
        title_hit = len(q_tokens & tokenize(title))
        score = overlap + 0.5 * title_hit
        scored.append((node_id, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return [node_id for node_id, _ in scored[:limit]]


def score_ranked_sessions(
    ranked_ids: Sequence[str],
    gold: set[str],
    *,
    k: int = 5,
) -> dict[str, float]:
    """Standard IR scores used in adapter aggregate tables.

    ``r@5`` uses LongMemEval-style ``recall_any@k`` (any gold in top-k) so sparse
    session haystacks match the agentmemory protocol. Also reports classic
    set-recall and precision for denser corpora.
    """
    top = list(ranked_ids)[:k]
    recall_any = 1.0 if gold & set(top) else 0.0
    return {
        "r@5": recall_any,
        "recall_set@5": recall_at_k(ranked_ids, gold, k),
        "p@5": precision_at_k(ranked_ids, gold, k),
        "mrr": mrr(ranked_ids, gold),
    }


def write_ndjson(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
