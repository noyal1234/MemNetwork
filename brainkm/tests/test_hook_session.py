"""Tests for last_hook_session inference and runtime_metric isolation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from brainkm.db.connection import connect
from brainkm.db.migrate import migrate
from brainkm.db.paths import brain_db_path
from brainkm.services.brain_stats import collect_brain_stats
from brainkm.services.hook_session import (
    CONFLICT_WINDOW_S,
    DEFAULT_MAX_AGE_S,
    clear_hook_session_caches_for_tests,
    get_last_hook_session,
    infer_session_id_if_missing,
    maybe_record_first_brainkm_call,
    record_runtime_metric,
    set_last_hook_session,
)
from brainkm.services.memory import new_ulid
from brainkm.services.session_activity import record_mcp_tool_use


def test_set_and_get_last_hook_session(tmp_path: Path) -> None:
    clear_hook_session_caches_for_tests()
    migrate(project_dir=tmp_path, run_integrity_check=False)
    set_last_hook_session(
        session_id="sess-a", client="claude", project_dir=tmp_path
    )
    conn = connect(brain_db_path(tmp_path))
    try:
        got = get_last_hook_session(conn)
        assert got is not None
        assert got.session_id == "sess-a"
        inferred, did = infer_session_id_if_missing(conn, None)
        assert did is True
        assert inferred == "sess-a"
        conn.commit()
    finally:
        conn.close()


def test_staleness_boundary_24h(tmp_path: Path) -> None:
    clear_hook_session_caches_for_tests()
    migrate(project_dir=tmp_path, run_integrity_check=False)
    set_last_hook_session(session_id="sess-stale", project_dir=tmp_path)
    conn = connect(brain_db_path(tmp_path))
    try:
        fresh = (datetime.now(UTC) - timedelta(hours=23, minutes=59)).isoformat()
        stale = (datetime.now(UTC) - timedelta(hours=24, minutes=1)).isoformat()
        conn.execute(
            "UPDATE brain_runtime SET updated_at = ? WHERE key = 'last_hook_session'",
            (fresh,),
        )
        conn.commit()
        clear_hook_session_caches_for_tests()
        assert get_last_hook_session(conn, max_age_s=DEFAULT_MAX_AGE_S) is not None

        conn.execute(
            "UPDATE brain_runtime SET updated_at = ? WHERE key = 'last_hook_session'",
            (stale,),
        )
        conn.commit()
        clear_hook_session_caches_for_tests()
        assert get_last_hook_session(conn, max_age_s=DEFAULT_MAX_AGE_S) is None
    finally:
        conn.close()


def test_concurrent_session_conflict_within_60s(tmp_path: Path) -> None:
    clear_hook_session_caches_for_tests()
    migrate(project_dir=tmp_path, run_integrity_check=False)
    set_last_hook_session(session_id="sess-a", project_dir=tmp_path)
    set_last_hook_session(session_id="sess-b", project_dir=tmp_path)
    conn = connect(brain_db_path(tmp_path))
    try:
        got = get_last_hook_session(conn)
        assert got is not None
        assert got.session_id == "sess-b"
        n = conn.execute(
            """
            SELECT COUNT(*) AS c FROM session_activity
            WHERE kind = 'runtime_metric' AND tool_name = 'concurrent_session_conflict'
            """
        ).fetchone()["c"]
        assert n >= 1
    finally:
        conn.close()


def test_same_session_refresh_no_conflict(tmp_path: Path) -> None:
    clear_hook_session_caches_for_tests()
    migrate(project_dir=tmp_path, run_integrity_check=False)
    set_last_hook_session(session_id="sess-same", project_dir=tmp_path)
    set_last_hook_session(session_id="sess-same", project_dir=tmp_path)
    conn = connect(brain_db_path(tmp_path))
    try:
        n = conn.execute(
            """
            SELECT COUNT(*) AS c FROM session_activity
            WHERE kind = 'runtime_metric' AND tool_name = 'concurrent_session_conflict'
            """
        ).fetchone()["c"]
        assert n == 0
        assert CONFLICT_WINDOW_S == 60
    finally:
        conn.close()


def test_first_brainkm_call_once_per_process(tmp_path: Path) -> None:
    clear_hook_session_caches_for_tests()
    migrate(project_dir=tmp_path, run_integrity_check=False)
    conn = connect(brain_db_path(tmp_path))
    try:
        maybe_record_first_brainkm_call(conn, "sess-first")
        maybe_record_first_brainkm_call(conn, "sess-first")
        conn.commit()
        n = conn.execute(
            """
            SELECT COUNT(*) AS c FROM session_activity
            WHERE kind = 'runtime_metric'
              AND tool_name = 'first_brainkm_call_this_session'
              AND session_id = 'sess-first'
            """
        ).fetchone()["c"]
        assert n == 1
    finally:
        conn.close()


def test_runtime_metric_does_not_inflate_mcp_calls(tmp_path: Path) -> None:
    clear_hook_session_caches_for_tests()
    migrate(project_dir=tmp_path, run_integrity_check=False)
    conn = connect(brain_db_path(tmp_path))
    try:
        record_mcp_tool_use(conn, "sess-x", "recall", result_count=1)
        record_runtime_metric(
            conn, session_id="sess-x", name="toolsearch_lead_in_shown"
        )
        record_runtime_metric(
            conn, session_id="sess-x", name="session_id_inferred", source="mcp"
        )
        conn.commit()
        from brainkm.models.brain_config import BrainConfig

        stats = collect_brain_stats(conn, config=BrainConfig(), project_dir=tmp_path)
        assert stats.mcp_calls_30d == 1
        assert any(k.startswith("recall") for k in stats.mcp_calls_by_tool)
    finally:
        conn.close()
