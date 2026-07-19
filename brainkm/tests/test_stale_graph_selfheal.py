"""Stale-graph reads should auto-queue graph sync."""

from __future__ import annotations

from pathlib import Path

from brainkm.db.connection import connect
from brainkm.db.migrate import migrate
from brainkm.models.brain_config import BrainConfig
from brainkm.models.schemas import ContextPackRequest, TraverseRequest
from brainkm.tools.dispatch import handle_context_pack, handle_traverse
from tests.conftest import insert_node


def test_context_pack_queues_sync_when_graph_stale(tmp_path: Path, monkeypatch) -> None:
    migrate(db_path=tmp_path / ".brain" / "brain.db", run_integrity_check=True)
    (tmp_path / "graphify-out").mkdir(parents=True, exist_ok=True)
    (tmp_path / "graphify-out" / "graph.json").write_text("{}", encoding="utf-8")

    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        insert_node(
            conn,
            node_id="d1",
            subtype="decision",
            title="Use FTS5",
            content="Prefer SQLite FTS5",
        )
        conn.commit()

        monkeypatch.setattr(
            "brainkm.services.graphify_sync.graph_json_newer_than_import",
            lambda *_a, **_k: True,
        )
        cfg = BrainConfig(
            recall={"abstain_on_low_confidence": False},
            graphify={"enabled": True, "auto_sync": {"enabled": True}},
        )
        result = handle_context_pack(
            conn,
            ContextPackRequest(query="FTS5"),
            config=cfg,
            project_dir=tmp_path,
        )
        assert (tmp_path / ".brain" / "graph_sync.requested").is_file()
        assert result.graph_hint is not None
        assert "graph refresh queued" in result.graph_hint
        assert result.confidence in {"high", "medium", "low"}
    finally:
        conn.close()


def test_traverse_queues_sync_when_graph_stale(tmp_path: Path, monkeypatch) -> None:
    migrate(db_path=tmp_path / ".brain" / "brain.db", run_integrity_check=True)
    (tmp_path / "graphify-out").mkdir(parents=True, exist_ok=True)
    (tmp_path / "graphify-out" / "graph.json").write_text("{}", encoding="utf-8")

    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        insert_node(conn, node_id="a", kind="code", subtype="file", title="a.py", path="a.py")
        conn.commit()
        monkeypatch.setattr(
            "brainkm.services.graphify_sync.graph_json_newer_than_import",
            lambda *_a, **_k: True,
        )
        result = handle_traverse(
            conn,
            TraverseRequest(from_ref="a.py"),
            config=BrainConfig(graphify={"enabled": True, "auto_sync": {"enabled": True}}),
            project_dir=tmp_path,
        )
        assert (tmp_path / ".brain" / "graph_sync.requested").is_file()
        assert result.hint is not None
        assert "graph refresh queued" in result.hint
    finally:
        conn.close()
