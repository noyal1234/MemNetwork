"""Cross-process last-hook session binding for MCP session_id inference.

Hooks (CLI subprocesses) and the MCP server share only SQLite. Writers use a
dedicated connection + BEGIN IMMEDIATE so they never nest inside SessionStart's
open transaction. Readers use an in-process TTL cache on the MCP hot path.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from brainkm.db.connection import connect
from brainkm.db.paths import brain_db_path
from brainkm.logging_config import get_logger
from brainkm.services.audit import utc_now_iso
from brainkm.services.memory import new_ulid
from brainkm.services.session_activity import ANON_SESSION_ID

logger = get_logger("services.hook_session")

LAST_HOOK_SESSION_KEY = "last_hook_session"
# Dead-session backstop only — UserPromptSubmit refreshes updated_at during
# active use; do not treat this as session lifetime.
DEFAULT_MAX_AGE_S = 86400
CONFLICT_WINDOW_S = 60
_CACHE_TTL_S = 4.0

_cache_value: LastHookSession | None = None
_cache_row_updated_at: str | None = None
_cache_loaded_at: float = 0.0
_first_brainkm_call_seen: set[str] = set()


@dataclass(frozen=True)
class LastHookSession:
    session_id: str
    client: str | None
    updated_at: str
    transcript_path: str | None = None


def _parse_iso(ts: str) -> datetime:
    cleaned = ts.replace("Z", "+00:00")
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _age_seconds(updated_at: str, *, now: datetime | None = None) -> float:
    now_dt = now or datetime.now(UTC)
    return max(0.0, (now_dt - _parse_iso(updated_at)).total_seconds())


def record_runtime_metric(
    conn: sqlite3.Connection,
    *,
    session_id: str | None,
    name: str,
    source: str = "hook",
) -> None:
    """Insert a non-usage funnel/conflict event (kind=runtime_metric)."""
    if not name:
        return
    sid = session_id or ANON_SESSION_ID
    conn.execute(
        """
        INSERT INTO session_activity (
          id, session_id, kind, node_id, tool_name, source, created_at
        ) VALUES (?, ?, 'runtime_metric', NULL, ?, ?, ?)
        """,
        (new_ulid(), sid, name, source, utc_now_iso()),
    )


def set_last_hook_session(
    *,
    session_id: str,
    client: str | None = None,
    transcript_path: Path | str | None = None,
    project_dir: Path | None = None,
    db_path: Path | None = None,
) -> None:
    """Upsert last_hook_session on a dedicated connection (BEGIN IMMEDIATE).

    ``transcript_path`` is optional per call site — SessionStart usually has
    it, UserPromptSubmit often does not re-derive it. When omitted (None) for
    the *same* session_id already cached, the previously cached path is kept
    rather than overwritten with None, so a later ``checkpoint`` MCP call can
    still resolve it. A different session_id always starts fresh (an old
    session's transcript path must never leak into a new one).
    """
    if not session_id or session_id == ANON_SESSION_ID:
        return
    path = db_path if db_path is not None else brain_db_path(project_dir)
    conn = connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT value, updated_at FROM brain_runtime WHERE key = ?",
                (LAST_HOOK_SESSION_KEY,),
            ).fetchone()
            now = utc_now_iso()
            resolved_transcript_path = str(transcript_path) if transcript_path else None
            if row is not None:
                try:
                    prev = json.loads(row["value"])
                    prev_sid = str(prev.get("session_id") or "")
                    age = _age_seconds(row["updated_at"])
                    if (
                        prev_sid
                        and prev_sid != session_id
                        and age < CONFLICT_WINDOW_S
                    ):
                        record_runtime_metric(
                            conn,
                            session_id=session_id,
                            name="concurrent_session_conflict",
                            source="hook",
                        )
                    if resolved_transcript_path is None and prev_sid == session_id:
                        resolved_transcript_path = prev.get("transcript_path")
                except (TypeError, ValueError, json.JSONDecodeError):
                    pass
            payload = json.dumps(
                {
                    "session_id": session_id,
                    "client": client,
                    "transcript_path": resolved_transcript_path,
                },
                separators=(",", ":"),
            )
            conn.execute(
                """
                INSERT INTO brain_runtime (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                  value = excluded.value,
                  updated_at = excluded.updated_at
                """,
                (LAST_HOOK_SESSION_KEY, payload, now),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    except sqlite3.OperationalError as exc:
        # Table missing before migrate — hooks must stay fail-soft.
        logger.warning("set_last_hook_session skipped: %s", exc)
    finally:
        conn.close()
    # Invalidate MCP-process cache if any (hooks don't share this process).
    global _cache_value, _cache_row_updated_at, _cache_loaded_at
    _cache_value = None
    _cache_row_updated_at = None
    _cache_loaded_at = 0.0


def get_last_hook_session(
    conn: sqlite3.Connection,
    *,
    max_age_s: float = DEFAULT_MAX_AGE_S,
) -> LastHookSession | None:
    """Return last hook session if fresher than max_age_s (TTL-cached in-process)."""
    global _cache_value, _cache_row_updated_at, _cache_loaded_at
    now_mono = time.monotonic()
    if (
        _cache_value is not None
        and _cache_row_updated_at is not None
        and (now_mono - _cache_loaded_at) < _CACHE_TTL_S
    ):
        if _age_seconds(_cache_row_updated_at) <= max_age_s:
            return _cache_value
        return None

    row = conn.execute(
        "SELECT value, updated_at FROM brain_runtime WHERE key = ?",
        (LAST_HOOK_SESSION_KEY,),
    ).fetchone()
    _cache_loaded_at = now_mono
    if row is None:
        _cache_value = None
        _cache_row_updated_at = None
        return None
    _cache_row_updated_at = row["updated_at"]
    if _age_seconds(row["updated_at"]) > max_age_s:
        _cache_value = None
        return None
    try:
        data = json.loads(row["value"])
        sid = str(data.get("session_id") or "").strip()
        if not sid:
            _cache_value = None
            return None
        client = data.get("client")
        transcript_path = data.get("transcript_path")
        parsed = LastHookSession(
            session_id=sid,
            client=str(client) if client else None,
            updated_at=row["updated_at"],
            transcript_path=str(transcript_path) if transcript_path else None,
        )
        _cache_value = parsed
        return parsed
    except (TypeError, ValueError, json.JSONDecodeError):
        _cache_value = None
        return None


def get_last_transcript_path(
    conn: sqlite3.Connection,
    session_id: str | None,
    *,
    max_age_s: float = DEFAULT_MAX_AGE_S,
) -> Path | None:
    """Resolve the transcript path cached for ``session_id`` (checkpoint MCP tool).

    This is a single-slot cache (one "last hook session" row, not a per-session
    map) — if ``session_id`` doesn't match what's cached, return None rather
    than handing back a different session's transcript path. ``session_id is
    None`` accepts whatever is cached (best-effort inference path).
    """
    cached = get_last_hook_session(conn, max_age_s=max_age_s)
    if cached is None or not cached.transcript_path:
        return None
    if session_id and cached.session_id != session_id:
        return None
    return Path(cached.transcript_path)


def maybe_record_first_brainkm_call(
    conn: sqlite3.Connection,
    session_id: str | None,
) -> None:
    """Record first_brainkm_call_this_session at most once per sid per MCP process."""
    if not session_id or session_id == ANON_SESSION_ID:
        return
    if session_id in _first_brainkm_call_seen:
        return
    _first_brainkm_call_seen.add(session_id)
    record_runtime_metric(
        conn,
        session_id=session_id,
        name="first_brainkm_call_this_session",
        source="mcp",
    )


def clear_hook_session_caches_for_tests() -> None:
    """Reset in-process caches (tests only)."""
    global _cache_value, _cache_row_updated_at, _cache_loaded_at
    _cache_value = None
    _cache_row_updated_at = None
    _cache_loaded_at = 0.0
    _first_brainkm_call_seen.clear()


def infer_session_id_if_missing(
    conn: sqlite3.Connection,
    session_id: str | None,
) -> tuple[str | None, bool]:
    """Return (session_id, inferred). Fills from last_hook_session when blank."""
    if (session_id or "").strip():
        return session_id, False
    cached = get_last_hook_session(conn, max_age_s=DEFAULT_MAX_AGE_S)
    if cached is None:
        return None, False
    record_runtime_metric(
        conn,
        session_id=cached.session_id,
        name="session_id_inferred",
        source="mcp",
    )
    return cached.session_id, True
