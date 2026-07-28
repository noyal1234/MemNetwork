"""Write-time and pack-level compression / diversity helpers."""

from __future__ import annotations

import logging
import re

from brainkm.adapters.embeddings import cosine_similarity, get_embedder
from brainkm.services.budget import BudgetLine
from brainkm.services.memory import token_count

logger = logging.getLogger(__name__)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def compress_body(
    content: str,
    *,
    max_tokens: int = 120,
    kind: str | None = None,
    subtype: str | None = None,
    project_dir: object | None = None,
    use_pipeline: bool = True,
) -> str:
    """Compress body via content-class pipeline then extractive cap.

    Decision/rule bodies are not lossy-rewritten here (pipeline
    ``allow_decision_lossy=False``); extractive still applies as a hard cap.
    """
    from pathlib import Path

    text = content.strip()
    if not text or token_count(text) <= max_tokens:
        return text

    if use_pipeline:
        from brainkm.services.compression.pipeline import compress_text

        result = compress_text(
            text,
            kind=kind,
            subtype=subtype,
            project_dir=Path(project_dir) if project_dir is not None else None,
            allow_decision_lossy=False,
        )
        text = result.text.strip() or content.strip()
        # Best-effort event log when project brain is available
        if project_dir is not None and result.stages:
            try:
                from brainkm.db.connection import connection
                from brainkm.services.compression.dual_store import log_compression_event

                with connection(project_dir=Path(project_dir)) as conn:
                    for stage in result.stages:
                        log_compression_event(
                            conn,
                            session_id=None,
                            surface="observe_write"
                            if subtype == "observation"
                            else "capture_write",
                            composition_mode="A",
                            engine_id=stage.engine_id,
                            tokens_in=stage.tokens_in,
                            tokens_out=stage.tokens_out,
                            skipped_reason=stage.skipped_reason,
                            latency_ms=stage.latency_ms,
                        )
            except Exception:
                logger.debug("compression event log failed", exc_info=True)
        if token_count(text) <= max_tokens:
            return text

    return _extractive_cap(text, max_tokens=max_tokens)


def _extractive_cap(text: str, *, max_tokens: int) -> str:
    """Extractive compression: keep highest-signal sentences under a token budget."""
    if not text or token_count(text) <= max_tokens:
        return text

    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    if not sentences:
        return text[: max_tokens * 4]

    # Score: prefer early sentences + length + keyword density.
    keywords = {
        "because",
        "decision",
        "chose",
        "instead",
        "must",
        "never",
        "always",
        "error",
        "fix",
        "prefer",
        "reject",
        "adopt",
    }

    scored: list[tuple[float, int, str]] = []
    for idx, sentence in enumerate(sentences):
        words = set(sentence.lower().split())
        kw = len(words & keywords)
        position = 1.0 / (1.0 + idx)
        length_penalty = min(1.0, 40.0 / max(1, len(sentence.split())))
        score = position * 2.0 + kw * 1.5 + length_penalty
        scored.append((score, idx, sentence))

    scored.sort(key=lambda item: item[0], reverse=True)
    selected: list[tuple[int, str]] = []
    used = 0
    for _, idx, sentence in scored:
        cost = token_count(sentence)
        if used + cost > max_tokens and selected:
            continue
        selected.append((idx, sentence))
        used += cost
        if used >= max_tokens:
            break

    selected.sort(key=lambda item: item[0])
    return " ".join(s for _, s in selected) if selected else sentences[0]


def shingle_set(text: str, *, n: int = 3) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    if len(tokens) < n:
        return set(tokens)
    return {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def dedup_budget_lines(
    lines: list[BudgetLine],
    *,
    threshold: float = 0.55,
    use_embeddings: bool = False,
) -> list[BudgetLine]:
    """Drop near-duplicate budget lines, keeping higher-priority (lower priority int) first."""
    ordered = sorted(lines, key=lambda line: (line.priority, -line.tokens))
    kept: list[BudgetLine] = []
    kept_shingles: list[set[str]] = []
    kept_vecs: list[list[float]] = []
    embedder = get_embedder(prefer_onnx=False) if use_embeddings else None

    for line in ordered:
        blob = f"{line.title}\n{line.content}"
        shingles = shingle_set(blob)
        vec = embedder.embed(blob) if embedder is not None else None
        duplicate = False
        for idx, other in enumerate(kept_shingles):
            if jaccard(shingles, other) >= threshold:
                duplicate = True
                break
            if vec is not None and kept_vecs[idx]:
                if cosine_similarity(vec, kept_vecs[idx]) >= 0.92:
                    duplicate = True
                    break
        if duplicate:
            continue
        kept.append(line)
        kept_shingles.append(shingles)
        kept_vecs.append(vec or [])
    # Restore original priority-ish order among kept
    kept.sort(key=lambda line: line.priority)
    return kept


def mmr_diversify(
    lines: list[BudgetLine],
    *,
    lambda_mult: float = 0.7,
    limit: int | None = None,
) -> list[BudgetLine]:
    """Maximal Marginal Relevance over title/content shingles."""
    if not lines:
        return []
    remaining = list(lines)
    selected: list[BudgetLine] = []
    selected_shingles: list[set[str]] = []

    while remaining and (limit is None or len(selected) < limit):
        best_idx = 0
        best_score = float("-inf")
        for idx, line in enumerate(remaining):
            relevance = 1.0 / (1.0 + line.priority)
            shingles = shingle_set(f"{line.title}\n{line.content}")
            max_sim = 0.0
            for other in selected_shingles:
                max_sim = max(max_sim, jaccard(shingles, other))
            score = lambda_mult * relevance - (1.0 - lambda_mult) * max_sim
            if score > best_score:
                best_score = score
                best_idx = idx
        chosen = remaining.pop(best_idx)
        selected.append(chosen)
        selected_shingles.append(shingle_set(f"{chosen.title}\n{chosen.content}"))
    return selected
