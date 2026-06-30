"""Tests for atomic Graphify graph.json import."""

import json
from pathlib import Path

import pytest

from brainkm.db.connection import connect
from brainkm.models.brain_config import BrainConfig
from brainkm.services.graph_import import import_graph_json, import_project_graph
from tests.conftest import insert_node
from tests.test_graphify_adapter import FIXTURE


def test_import_graph_json_persists_code_nodes_and_edges(brain_db, tmp_path: Path) -> None:
    result = import_graph_json(
        FIXTURE,
        db_path=brain_db,
        config=BrainConfig(graphify={"code_only": True}),
    )

    assert result.status == "completed"
    assert result.node_count == 3
    assert result.edge_count == 2

    conn = connect(brain_db)
    try:
        code_nodes = conn.execute(
            "SELECT id, subtype FROM nodes WHERE kind = 'code' ORDER BY id"
        ).fetchall()
        assert len(code_nodes) == 3
        subtypes = {row[1] for row in code_nodes}
        assert "file" in subtypes
        assert "function" in subtypes

        edge = conn.execute(
            "SELECT relationship, weight FROM edges WHERE from_id = ? AND to_id = ?",
            ("auth", "models"),
        ).fetchone()
        assert edge[0] == "imports_from"
        assert edge[1] == 1.0

        run = conn.execute(
            """
            SELECT status, node_count, edge_count, completed_at
            FROM graph_import_runs WHERE id = ?
            """,
            (result.run_id,),
        ).fetchone()
        assert run[0] == "completed"
        assert run[1] == 3
        assert run[2] == 2
        assert run[3] is not None
    finally:
        conn.close()


def test_import_replaces_previous_code_graph_without_touching_memory(brain_db) -> None:
    conn = connect(brain_db)
    try:
        insert_node(
            conn,
            node_id="memory-1",
            kind="memory",
            subtype="decision",
            title="Use SQLite",
        )
        conn.commit()
    finally:
        conn.close()

    first = import_graph_json(
        FIXTURE,
        db_path=brain_db,
        config=BrainConfig(graphify={"code_only": True}),
    )
    assert first.node_count == 3

    second = import_graph_json(
        FIXTURE,
        db_path=brain_db,
        config=BrainConfig(graphify={"code_only": True}),
    )
    assert second.node_count == 3

    conn = connect(brain_db)
    try:
        memory_count = conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE kind = 'memory'"
        ).fetchone()[0]
        code_count = conn.execute("SELECT COUNT(*) FROM nodes WHERE kind = 'code'").fetchone()[0]
        import_runs = conn.execute("SELECT COUNT(*) FROM graph_import_runs").fetchone()[0]
        assert memory_count == 1
        assert code_count == 3
        assert import_runs == 2
    finally:
        conn.close()


def test_import_project_graph_uses_config_path(brain_db, tmp_path: Path) -> None:
    graph_dir = tmp_path / "graphify-out"
    graph_dir.mkdir()
    graph_path = graph_dir / "graph.json"
    graph_path.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    config = BrainConfig(graphify={"graph_json": "graphify-out/graph.json", "code_only": True})
    result = import_project_graph(project_dir=tmp_path, config=config, db_path=brain_db)
    assert result.status == "completed"
    assert result.node_count == 3


def test_import_project_graph_missing_file_raises(brain_db, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        import_project_graph(
            project_dir=tmp_path,
            config=BrainConfig(),
            db_path=brain_db,
        )


def test_import_skipped_when_graphify_disabled(brain_db, tmp_path: Path) -> None:
    result = import_project_graph(
        project_dir=tmp_path,
        config=BrainConfig(graphify={"enabled": False}),
        db_path=brain_db,
    )
    assert result.status == "skipped"


def test_import_skipped_empty_preserves_code_nodes(brain_db, tmp_path: Path) -> None:
    import_graph_json(FIXTURE, db_path=brain_db, config=BrainConfig(graphify={"code_only": True}))

    docs_only = tmp_path / "docs_only.json"
    docs_only.write_text(
        json.dumps(
            {
                "nodes": [{"id": "d1", "label": "doc", "file_type": "document"}],
                "links": [],
            }
        ),
        encoding="utf-8",
    )
    result = import_graph_json(
        docs_only,
        db_path=brain_db,
        config=BrainConfig(graphify={"code_only": True}),
    )
    assert result.status == "skipped_empty"

    conn = connect(brain_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM nodes WHERE kind = 'code'").fetchone()[0] == 3
    finally:
        conn.close()
