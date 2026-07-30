"""Tests for per-tool success/failure counters (migration 012_tool_feedback)."""

from __future__ import annotations

import json

from brainkm.db.connection import connect
from brainkm.services.hooks import run_post_tool_use
from brainkm.services.tool_feedback import get_tool_feedback, record_tool_result


def test_record_tool_result_success_then_failure(brain_db) -> None:
    conn = connect(brain_db)
    try:
        record_tool_result(conn, "Shell", failed=False)
        conn.commit()
        summary = get_tool_feedback(conn, "Shell")
        assert summary is not None
        assert summary.success_count == 1
        assert summary.failure_count == 0
        assert summary.last_failure is None

        record_tool_result(conn, "Shell", failed=True)
        conn.commit()
        summary2 = get_tool_feedback(conn, "Shell")
        assert summary2 is not None
        assert summary2.success_count == 1
        assert summary2.failure_count == 1
        assert summary2.last_failure is not None
    finally:
        conn.close()


def test_get_tool_feedback_missing_tool_returns_none(brain_db) -> None:
    conn = connect(brain_db)
    try:
        assert get_tool_feedback(conn, "NeverCalled") is None
    finally:
        conn.close()


def test_run_post_tool_use_records_success(tmp_path) -> None:
    from brainkm.db.migrate import migrate

    migrate(project_dir=tmp_path, run_integrity_check=False)
    run_post_tool_use(
        json.dumps({"tool_name": "Edit", "session_id": "sess-tf-1"}),
        project_dir=tmp_path,
        failed=False,
    )
    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        summary = get_tool_feedback(conn, "Edit")
        assert summary is not None
        assert summary.success_count == 1
        assert summary.failure_count == 0
    finally:
        conn.close()


def test_run_post_tool_use_records_failure(tmp_path) -> None:
    from brainkm.db.migrate import migrate

    migrate(project_dir=tmp_path, run_integrity_check=False)
    run_post_tool_use(
        json.dumps({"tool_name": "Bash", "session_id": "sess-tf-2"}),
        project_dir=tmp_path,
        failed=True,
    )
    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        summary = get_tool_feedback(conn, "Bash")
        assert summary is not None
        assert summary.success_count == 0
        assert summary.failure_count == 1
        assert summary.last_failure is not None
    finally:
        conn.close()
