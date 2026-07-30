"""Passive hook observations — capped, deduped, promoted on SessionEnd."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from brainkm.logging_config import get_logger
from brainkm.models.brain_config import BrainConfig
from brainkm.services.memory import forget_neuron, remember_neuron, token_count
from brainkm.services.quality import passes_stored_neuron_gate
from brainkm.services.review import enqueue_for_review

logger = get_logger("services.observe")

OBSERVATION_SUBTYPE = "observation"
FP_TAG_PREFIX = "observe_fp:"
FAILED_TAG = "observe_failed"
_PATH_RE = re.compile(
    r"(?:['\"]|/|\./|\.\./)([\w./\\-]+\.\w{1,8})",
)


@dataclass(frozen=True)
class ObserveResult:
    stored: bool
    node_id: str | None = None
    skipped_reason: str | None = None


@dataclass(frozen=True)
class PromoteResult:
    scanned: int
    promoted: int
    archived: int
    review_queued: int


def _utc_now() -> datetime:
    return datetime.now(UTC)


def observation_fingerprint(
    *,
    tool: str,
    path: str | None,
    outcome: str,
    failed: bool,
) -> str:
    blob = f"{tool}|{path or ''}|{outcome}|{int(failed)}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def extract_observation_path(payload: dict[str, object]) -> str | None:
    for key in (
        "file_path",
        "path",
        "target_file",
        "filePath",
        "TargetFile",
        "AbsolutePath",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:240]
    tool_input = payload.get("tool_input") or payload.get("input")
    if isinstance(tool_input, dict):
        for key in (
            "file_path",
            "path",
            "target_file",
            "TargetFile",
            "AbsolutePath",
            "command",
        ):
            value = tool_input.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:240]
    text = json.dumps(payload, default=str)[:2000]
    match = _PATH_RE.search(text)
    if match:
        return match.group(1)[:240]
    return None


def _extract_path(payload: dict[str, object]) -> str | None:
    return extract_observation_path(payload)


def _one_line_outcome(payload: dict[str, object], *, failed: bool) -> str:
    """First line of the outcome — no hard char clip.

    Storage size is enforced later via ``capture.observe_max_body_tokens``.
    Premature char truncation (e.g. 120) mangled short durable facts before
    they reached the token budget and degraded promoted neuron quality.
    """
    if failed:
        for key in ("error", "message", "failure", "stderr"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().splitlines()[0].strip()
        tool_result = payload.get("tool_result") or payload.get("result")
        if isinstance(tool_result, str) and tool_result.strip():
            return tool_result.strip().splitlines()[0].strip()
        return "tool failed"
    status = payload.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip().splitlines()[0].strip()
    return "ok"


def _session_observation_count(conn: sqlite3.Connection, session_id: str) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM nodes
        WHERE kind = 'memory'
          AND subtype = ?
          AND valid_until IS NULL
          AND session_id = ?
        """,
        (OBSERVATION_SUBTYPE, session_id),
    ).fetchone()
    return int(row["n"] if row else 0)


def _recent_fingerprint_hit(
    conn: sqlite3.Connection,
    fingerprint: str,
    *,
    window_seconds: int,
) -> bool:
    cutoff = (_utc_now() - timedelta(seconds=window_seconds)).isoformat()
    tag = f"{FP_TAG_PREFIX}{fingerprint}"
    row = conn.execute(
        """
        SELECT 1 FROM nodes
        WHERE kind = 'memory'
          AND subtype = ?
          AND valid_until IS NULL
          AND created_at >= ?
          AND tags LIKE ?
        LIMIT 1
        """,
        (OBSERVATION_SUBTYPE, cutoff, f"%{tag}%"),
    ).fetchone()
    return row is not None


def record_observation(
    conn: sqlite3.Connection,
    *,
    session_id: str | None,
    tool_name: str,
    payload: dict[str, object],
    config: BrainConfig,
    failed: bool = False,
) -> ObserveResult:
    """Persist one capped observation when ``capture.auto_observe`` is enabled."""
    if not config.capture.auto_observe:
        return ObserveResult(stored=False, skipped_reason="auto_observe disabled")

    sid = session_id or "unknown"
    if _session_observation_count(conn, sid) >= config.capture.observe_max_per_session:
        logger.info("observe skipped session_id=%s reason=max_per_session", sid)
        return ObserveResult(stored=False, skipped_reason="max_per_session")

    path = _extract_path(payload)
    outcome = _one_line_outcome(payload, failed=failed)
    max_tok = config.capture.observe_max_body_tokens
    body = outcome
    if token_count(body) > max_tok:
        body = body[: max_tok * 4]
    # Fingerprint the body we will store so dedup matches retained text.
    fp = observation_fingerprint(
        tool=tool_name,
        path=path,
        outcome=body,
        failed=failed,
    )
    if _recent_fingerprint_hit(
        conn,
        fp,
        window_seconds=config.capture.observe_dedup_window_seconds,
    ):
        return ObserveResult(stored=False, skipped_reason="dedup_window")

    title = f"{'FAIL' if failed else 'tool'}: {tool_name}"
    if path:
        title = f"{title} → {path}"

    tags = [f"{FP_TAG_PREFIX}{fp}", f"tool:{tool_name}"]
    if failed:
        tags.append(FAILED_TAG)
    confidence = 0.35 if failed else 0.25
    try:
        record = remember_neuron(
            conn,
            title=title[:200],
            content=body,
            subtype=OBSERVATION_SUBTYPE,
            confidence=confidence,
            source="auto_observe",
            session_id=sid,
            path=path,
            tags=tags,
            compress=True,
            max_body_tokens=max_tok,
        )
    except Exception as exc:
        logger.warning("observe write failed: %s", exc)
        return ObserveResult(stored=False, skipped_reason=str(exc))

    return ObserveResult(stored=True, node_id=record.id)


def record_prompt_observation(
    conn: sqlite3.Connection,
    *,
    session_id: str | None,
    prompt: str,
    config: BrainConfig,
) -> ObserveResult:
    """Store a redacted prompt gist (not the full prompt)."""
    if not config.capture.auto_observe:
        return ObserveResult(stored=False, skipped_reason="auto_observe disabled")
    gist = " ".join(prompt.strip().split())[:160]
    if not gist:
        return ObserveResult(stored=False, skipped_reason="empty_prompt")
    payload: dict[str, object] = {"status": gist}
    return record_observation(
        conn,
        session_id=session_id,
        tool_name="UserPrompt",
        payload=payload,
        config=config,
        failed=False,
    )


def list_session_observations(
    conn: sqlite3.Connection,
    session_id: str,
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT id, title, content, confidence, tags, path
            FROM nodes
            WHERE kind = 'memory'
              AND subtype = ?
              AND valid_until IS NULL
              AND session_id = ?
            ORDER BY created_at ASC
            """,
            (OBSERVATION_SUBTYPE, session_id),
        ).fetchall()
    )


def promote_session_observations(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    config: BrainConfig,
    project_dir: object | None = None,
) -> PromoteResult:
    """Promote observations into decision/error neurons; archive raw rows."""
    from pathlib import Path

    from brainkm.services.lifecycle import insert_distilled_from_edge
    from brainkm.services.neuron_index import index_neuron_links

    rows = list_session_observations(conn, session_id)
    promoted = 0
    archived = 0
    review_queued = 0
    root = Path(project_dir) if project_dir is not None else None
    for row in rows:
        title = (row["title"] or "").strip()
        content = (row["content"] or "").strip()
        obs_path = row["path"] if "path" in row.keys() else None
        tags_raw = row["tags"] or "[]"
        try:
            tags = json.loads(tags_raw) if isinstance(tags_raw, str) else list(tags_raw)
        except json.JSONDecodeError:
            tags = []
        failed = FAILED_TAG in tags
        # A successful tool call is an observation, not a decision. Filing these
        # as `decision` put them in the same uncapped bucket as hand-pinned
        # architecture decisions, where they outranked the real ones in every
        # context_pack. `observation` is capped at 1 per pack (_PACK_MEMORY_CAPS).
        subtype = "error" if failed else OBSERVATION_SUBTYPE
        conf = 0.55 if failed else 0.45
        if not passes_stored_neuron_gate(title=title, content=content):
            forget_neuron(conn, row["id"], reason="observe_promote: failed quality gate")
            archived += 1
            continue
        new_title = title.replace("FAIL: ", "").replace("tool: ", "", 1)
        new_title = f"Error: {new_title}" if failed else f"Observed: {new_title}"
        try:
            record = remember_neuron(
                conn,
                title=new_title[:200],
                content=content,
                subtype=subtype,
                confidence=conf,
                source="observe_promote",
                session_id=session_id,
                path=obs_path,
                compress=True,
                max_body_tokens=config.compression.max_body_tokens,
            )
            insert_distilled_from_edge(conn, from_id=record.id, to_id=row["id"])
            index_neuron_links(
                conn,
                record.id,
                title=record.title,
                content=record.content,
                tags=tags,
                kind="memory",
            )
            promoted += 1
            if conf < config.learning.auto_capture_confidence:
                enqueue_for_review(conn, record.id, project_dir=root)
                review_queued += 1
        except Exception as exc:
            logger.warning("observe promote failed id=%s: %s", row["id"], exc)
        forget_neuron(conn, row["id"], reason="observe_promote: archived raw observation")
        archived += 1
    return PromoteResult(
        scanned=len(rows),
        promoted=promoted,
        archived=archived,
        review_queued=review_queued,
    )
