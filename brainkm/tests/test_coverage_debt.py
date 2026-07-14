"""Coverage for export, import_merge, repair, plan_capture, and review."""

from __future__ import annotations

import json
from pathlib import Path

from brainkm.db.connection import connect
from brainkm.models.brain_config import BrainConfig
from brainkm.services.export import export_markdown
from brainkm.services.import_merge import import_json_merge, import_neurons_merge
from brainkm.services.memory import create_neuron, remember_neuron
from brainkm.services.plan_capture import capture_plan_files
from brainkm.services.repair import repair_brain, rescan_neurons_for_secrets
from brainkm.services.review import (
    approve_pending,
    enqueue_for_review,
    list_pending,
    reject_pending,
)
from brainkm.tools.dispatch import handle_brain_stats
from brainkm.models.schemas import BrainStatsRequest
from tests.conftest import insert_node


def test_export_import_round_trip(tmp_path: Path, brain_db: Path) -> None:
    project = tmp_path
    conn = connect(brain_db)
    try:
        remember_neuron(
            conn,
            title="Use JWT for API auth",
            content="Access tokens expire after 15 minutes.",
            subtype="decision",
            confidence=0.9,
        )
        conn.commit()
    finally:
        conn.close()

    # markdown export
    md = export_markdown(project_dir=project)
    assert md.neuron_count >= 1
    assert md.path.is_file()
    assert "JWT" in md.path.read_text(encoding="utf-8")

    # JSON merge import into a fresh sibling brain via inline records
    conn = connect(brain_db)
    try:
        result = import_neurons_merge(
            conn,
            [
                {
                    "title": "Use JWT for API auth",
                    "content": "Rotated expiry to 30 minutes.",
                    "kind": "memory",
                    "subtype": "decision",
                    "confidence": 0.95,
                },
                {
                    "title": "Blocked secret should skip",
                    "content": "sk-live-abcdefghijklmnopqrstuvwxyz123456",
                    "confidence": 1.0,
                },
            ],
        )
        conn.commit()
        assert result.imported >= 1
        assert result.skipped >= 1
        active = conn.execute(
            "SELECT content FROM nodes WHERE title = ? AND valid_until IS NULL",
            ("Use JWT for API auth",),
        ).fetchone()
        assert active is not None
        assert "30 minutes" in active[0]
    finally:
        conn.close()

    export_path = tmp_path / "neurons.json"
    export_path.write_text(
        json.dumps(
            [
                {
                    "title": "Imported via file",
                    "content": "Prefer FTS5 for recall.",
                    "kind": "memory",
                    "subtype": "decision",
                    "confidence": 1.0,
                }
            ]
        ),
        encoding="utf-8",
    )
    file_result = import_json_merge(export_path, project_dir=project)
    assert file_result.imported == 1


def test_repair_rescan_and_fts(tmp_path: Path, brain_db: Path) -> None:
    conn = connect(brain_db)
    try:
        create_neuron(
            conn,
            title="Leak",
            content="sk-live-abcdefghijklmnopqrstuvwxyz123456",
            subtype="fact",
        )
        remember_neuron(conn, title="Clean", content="Use SQLite FTS5", subtype="fact")
        conn.commit()
        archived = rescan_neurons_for_secrets(conn)
        conn.commit()
        assert archived == 1
    finally:
        conn.close()

    result = repair_brain(project_dir=tmp_path, recalibrate_abstention=False)
    assert result.integrity_ok is True
    assert result.fts_rows_rebuilt >= 1


def test_plan_capture_creates_decision_neurons(tmp_path: Path, brain_db: Path, monkeypatch) -> None:
    plan_path = tmp_path / "auth.plan.md"
    plan_path.write_text(
        "## Decision\n\nWe decided to use JWT instead of session cookies.\n",
        encoding="utf-8",
    )

    from brainkm.models.distill import DistilledNeuron

    def fake_distill(path, *, config, conn=None):
        return [
            DistilledNeuron(
                subtype="decision",
                title="Use JWT for API auth",
                body="Access tokens expire after 15 minutes.",
                tags=["auth"],
                confidence=1.0,
            )
        ]

    monkeypatch.setattr(
        "brainkm.services.plan_capture.distill_plan_file",
        fake_distill,
    )
    monkeypatch.setattr(
        "brainkm.services.plan_capture.discover_plan_files",
        lambda project_dir, glob_pattern: [plan_path],
    )

    conn = connect(brain_db)
    try:
        count = capture_plan_files(
            conn,
            project_dir=tmp_path,
            config=BrainConfig(capture={"plan_files": True, "distill_mode": "rules"}),
        )
        conn.commit()
        assert count == 1
        row = conn.execute(
            "SELECT title, source FROM nodes WHERE valid_until IS NULL"
        ).fetchone()
        assert row is not None
        assert row[0] == "Use JWT for API auth"
        assert str(row[1]).startswith("plan:")
    finally:
        conn.close()


def test_review_enqueue_approve_reject(tmp_path: Path, brain_db: Path) -> None:
    conn = connect(brain_db)
    try:
        record = remember_neuron(
            conn,
            title="Low confidence capture",
            content="Maybe use Redis for sessions.",
            subtype="fact",
            confidence=0.3,
        )
        path = enqueue_for_review(conn, record.id, project_dir=tmp_path)
        conn.commit()
        assert path.is_file()
        pending = list_pending(tmp_path)
        assert any(item.node_id == record.id for item in pending)

        assert approve_pending(record.id, conn=conn, project_dir=tmp_path) is True
        assert list_pending(tmp_path) == []

        record2 = remember_neuron(
            conn,
            title="Reject me",
            content="Questionable fact to archive.",
            subtype="fact",
            confidence=0.2,
        )
        enqueue_for_review(conn, record2.id, project_dir=tmp_path)
        conn.commit()
        assert reject_pending(record2.id, conn=conn, project_dir=tmp_path) is True
        archived = conn.execute(
            "SELECT valid_until FROM nodes WHERE id = ?",
            (record2.id,),
        ).fetchone()
        assert archived is not None
        assert archived[0] is not None
    finally:
        conn.close()


def test_brain_stats_session_scoped_fields(tmp_path: Path, brain_db: Path) -> None:
    conn = connect(brain_db)
    try:
        insert_node(conn, node_id="n1", subtype="rule", title="Pinned rule")
        from brainkm.services.session_activity import record_mcp_tool_use, record_neuron_activity

        record_mcp_tool_use(conn, "sess-stats", "recall", result_count=2)
        record_neuron_activity(conn, "sess-stats", ["n1"], source="recall")
        conn.execute(
            """
            INSERT INTO session_snapshots (
              session_id, pack_text, neuron_ids, token_count, frozen, created_at
            ) VALUES (?, ?, ?, ?, 1, datetime('now'))
            """,
            ("sess-stats", "# pack", '["n1"]', 42),
        )
        conn.execute(
            """
            INSERT INTO ingested_sessions (
              session_id, fingerprint, distill_mode, neuron_count, ingested_at
            ) VALUES (?, ?, ?, ?, datetime('now'))
            """,
            ("sess-stats", "fp", "rules", 3),
        )
        conn.commit()
        stats = handle_brain_stats(
            conn,
            BrainStatsRequest(session_id="sess-stats"),
            config=BrainConfig(),
            project_dir=tmp_path,
        )
        assert stats.session_id == "sess-stats"
        assert stats.session_mcp_calls_by_tool.get("recall", 0) >= 1
        assert stats.session_neuron_hits >= 1
        assert stats.session_injection_tokens == 42
        assert stats.session_distill_mode == "rules"
        assert stats.session_neuron_count == 3
    finally:
        conn.close()
