"""Tests for Graphify sync orchestration."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from brainkm.models.brain_config import BrainConfig, GraphifyAutoSyncConfig, GraphifyConfig
from brainkm.services.graph_import import count_code_nodes, import_graph_json
from brainkm.services.graphify_sync import (
    GraphSyncScheduler,
    GraphifyArgsError,
    build_graph_status,
    probe_graphify,
    request_graph_sync,
    resolve_graphify_binary,
    sync_graph,
    validate_graphify_extra_args,
)
from brainkm.services.install import run_install
from tests.test_graphify_adapter import FIXTURE


def test_resolve_graphify_binary_absolute(tmp_path: Path) -> None:
    fake_bin = tmp_path / "graphify"
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    cfg = GraphifyConfig(extract_binary=str(fake_bin))
    assert resolve_graphify_binary(cfg) == fake_bin


def test_probe_graphify_missing() -> None:
    cfg = GraphifyConfig(extract_binary="/nonexistent/graphify-binary")
    result = probe_graphify(cfg)
    assert result.found is False
    assert result.reason is not None


def test_run_graphify_extract_uses_update_when_code_only(tmp_path: Path) -> None:
    from brainkm.services.graphify_sync import run_graphify_extract

    cfg = BrainConfig(graphify={"code_only": True, "graph_json": "graphify-out/graph.json"})
    graph_path = tmp_path / "graphify-out" / "graph.json"
    graph_path.parent.mkdir(parents=True)
    graph_path.write_text('{"nodes":[],"links":[]}', encoding="utf-8")

    with patch("brainkm.services.graphify_sync.probe_graphify") as mock_probe:
        mock_probe.return_value = MagicMock(found=True, binary_path="/fake/graphify", reason=None)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
            run_graphify_extract(tmp_path, cfg)
            cmd = mock_run.call_args[0][0]
            assert cmd[1] == "update"
            assert "--no-cluster" in cmd


def test_run_graphify_extract_uses_extract_when_not_code_only(tmp_path: Path) -> None:
    from brainkm.services.graphify_sync import run_graphify_extract

    cfg = BrainConfig(graphify={"code_only": False, "graph_json": "graphify-out/graph.json"})
    graph_path = tmp_path / "graphify-out" / "graph.json"
    graph_path.parent.mkdir(parents=True)
    graph_path.write_text('{"nodes":[],"links":[]}', encoding="utf-8")

    with patch("brainkm.services.graphify_sync.probe_graphify") as mock_probe:
        mock_probe.return_value = MagicMock(found=True, binary_path="/fake/graphify", reason=None)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
            run_graphify_extract(tmp_path, cfg)
            cmd = mock_run.call_args[0][0]
            assert cmd[1] == "extract"
            assert "--no-cluster" not in cmd


def test_sync_graph_imports_fixture(brain_db, tmp_path: Path) -> None:
    graph_dir = tmp_path / "graphify-out"
    graph_dir.mkdir()
    (graph_dir / "graph.json").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / ".brain").mkdir(exist_ok=True)
    config = BrainConfig(graphify={"graph_json": "graphify-out/graph.json", "code_only": True})

    with patch("brainkm.services.graphify_sync.import_project_graph") as mock_import:
        from brainkm.models.graphify import GraphImportResult

        mock_import.return_value = GraphImportResult(
            run_id="run1",
            status="completed",
            node_count=3,
            edge_count=2,
            skipped_non_code_nodes=0,
            skipped_edges=0,
            graph_path=str(graph_dir / "graph.json"),
        )
        result = sync_graph(tmp_path, config, extract=False)
    assert result.status == "completed"
    assert result.import_result is not None
    assert result.import_result.node_count == 3


def test_sync_graph_skips_empty_preserving_prior_graph(brain_db, tmp_path: Path) -> None:
    import_graph_json(FIXTURE, db_path=brain_db, config=BrainConfig(graphify={"code_only": True}))

    docs_only = {
        "nodes": [
            {
                "id": "readme_doc",
                "label": "README",
                "file_type": "document",
                "source_file": "README.md",
            }
        ],
        "links": [],
    }
    graph_dir = tmp_path / "graphify-out"
    graph_dir.mkdir()
    graph_path = graph_dir / "graph.json"
    graph_path.write_text(json.dumps(docs_only), encoding="utf-8")
    (tmp_path / ".brain").mkdir(exist_ok=True)

    config = BrainConfig(graphify={"graph_json": "graphify-out/graph.json", "code_only": True})
    with patch("brainkm.services.graphify_sync.brain_db_path", return_value=brain_db):
        result = sync_graph(tmp_path, config, extract=False)

    assert result.status == "skipped_empty"
    conn = __import__("brainkm.db.connection", fromlist=["connect"]).connect(brain_db)
    try:
        assert count_code_nodes(conn) == 3
    finally:
        conn.close()


def test_import_refuses_empty_when_code_exists(brain_db, tmp_path: Path) -> None:
    import_graph_json(FIXTURE, db_path=brain_db, config=BrainConfig(graphify={"code_only": True}))

    docs_only_path = tmp_path / "docs_only.json"
    docs_only_path.write_text(
        json.dumps(
            {
                "nodes": [{"id": "d1", "label": "doc", "file_type": "document"}],
                "links": [],
            }
        ),
        encoding="utf-8",
    )
    result = import_graph_json(
        docs_only_path,
        db_path=brain_db,
        config=BrainConfig(graphify={"code_only": True}),
    )
    assert result.status == "skipped_empty"
    conn = __import__("brainkm.db.connection", fromlist=["connect"]).connect(brain_db)
    try:
        assert count_code_nodes(conn) == 3
    finally:
        conn.close()


def test_import_rollback_preserves_graph_on_failure(
    brain_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = BrainConfig(graphify={"code_only": True})
    import_graph_json(FIXTURE, db_path=brain_db, config=cfg)

    def boom(conn, graph):  # noqa: ANN001
        raise sqlite3.OperationalError("simulated failure")

    monkeypatch.setattr(
        "brainkm.services.graph_import._insert_code_graph",
        boom,
    )
    with pytest.raises(sqlite3.OperationalError):
        import_graph_json(FIXTURE, db_path=brain_db, config=cfg)

    conn = __import__("brainkm.db.connection", fromlist=["connect"]).connect(brain_db)
    try:
        assert count_code_nodes(conn) == 3
    finally:
        conn.close()


def test_extract_failure_skips_import(brain_db, tmp_path: Path) -> None:
    import_graph_json(FIXTURE, db_path=brain_db, config=BrainConfig(graphify={"code_only": True}))
    (tmp_path / ".brain").mkdir(exist_ok=True)
    config = BrainConfig()

    with patch(
        "brainkm.services.graphify_sync.run_graphify_extract",
        return_value=MagicMock(ok=False, stderr_snippet="extract failed"),
    ):
        with patch("brainkm.services.graphify_sync.brain_db_path", return_value=brain_db):
            result = sync_graph(tmp_path, config, extract=True)

    assert result.status == "extract_failed"
    conn = __import__("brainkm.db.connection", fromlist=["connect"]).connect(brain_db)
    try:
        assert count_code_nodes(conn) == 3
    finally:
        conn.close()


def test_single_flight_lock_skips_concurrent_sync(tmp_path: Path) -> None:
    (tmp_path / ".brain").mkdir(exist_ok=True)
    lock = tmp_path / ".brain" / "graph_sync.lock"
    lock.write_text("", encoding="utf-8")
    config = BrainConfig()
    result = sync_graph(tmp_path, config, extract=False)
    assert result.status == "skipped_locked"


def test_request_graph_sync_creates_flag(tmp_path: Path) -> None:
    request_graph_sync(tmp_path)
    flag = tmp_path / ".brain" / "graph_sync.requested"
    assert flag.is_file()


def test_scheduler_debounce_respects_min_interval(tmp_path: Path) -> None:
    (tmp_path / ".brain").mkdir(exist_ok=True)
    config = BrainConfig(
        graphify={
            "auto_sync": GraphifyAutoSyncConfig(
                enabled=True,
                debounce_seconds=1.0,
                min_interval_seconds=3600.0,
            )
        }
    )
    scheduler = GraphSyncScheduler(tmp_path, config)
    calls: list[str] = []

    def fake_sync(*args, **kwargs):  # noqa: ANN002, ANN003
        from brainkm.models.graphify import GraphSyncResult

        calls.append("sync")
        return GraphSyncResult(status="completed", graph_available=True)

    with patch("brainkm.services.graphify_sync.sync_graph", side_effect=fake_sync):
        with patch(
            "brainkm.services.graphify_sync.seconds_since_last_successful_sync",
            return_value=10.0,
        ):
            scheduler._schedule_sync(reason="test")
            time.sleep(1.2)
    assert calls == []


def test_build_graph_status(tmp_path: Path) -> None:
    status = build_graph_status(tmp_path, BrainConfig())
    assert "graphify_found" in status
    assert status["auto_sync_enabled"] is True


def test_install_warns_when_sync_fails(tmp_path: Path) -> None:
    with patch("brainkm.services.graphify_sync.sync_graph", side_effect=RuntimeError("boom")):
        with patch(
            "brainkm.services.graphify_sync.probe_graphify",
            return_value=MagicMock(found=True, binary_path="/usr/bin/graphify", reason=None),
        ):
            with patch("brainkm.services.install.migrate"):
                with patch("brainkm.services.install._write_json"):
                    with patch("brainkm.services.install._write_text"):
                        with patch(
                            "brainkm.services.abstention_calibrate.calibrate_reference",
                        ):
                            with patch(
                                "brainkm.services.install.build_mcp_config",
                                return_value={"mcpServers": {}},
                            ):
                                with patch(
                                    "brainkm.services.install.build_hooks_config",
                                    return_value={"version": 1, "hooks": {}},
                                ):
                                    with patch(
                                        "brainkm.services.install.resolve_hook_command",
                                        return_value="brainkm",
                                    ):
                                        result = run_install(
                                            tmp_path,
                                            dev=True,
                                            force=True,
                                            config=BrainConfig(
                                                graphify={"sync_on_install": True}
                                            ),
                                        )
    assert any("graph sync skipped" in w for w in result.warnings)


def test_graph_status_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    from brainkm.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["graph", "status"])
    assert result.exit_code == 0
    assert "graph_available" in result.stdout


def test_graph_sync_cli_with_skip_extract(
    brain_db, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph_dir = tmp_path / "graphify-out"
    graph_dir.mkdir()
    (graph_dir / "graph.json").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / ".brain").mkdir(exist_ok=True)
    monkeypatch.chdir(tmp_path)

    from brainkm.cli import app

    with patch("brainkm.services.graphify_sync.brain_db_path", return_value=brain_db):
        runner = CliRunner()
        result = runner.invoke(app, ["graph", "sync", "--skip-extract"])
    assert result.exit_code == 0
    assert "Synced graph" in result.stdout or "Skipped" in result.stdout


def test_validate_graphify_extra_args_allowlist() -> None:
    assert validate_graphify_extra_args(["--no-cluster", "--exclude=vendor"]) == [
        "--no-cluster",
        "--exclude=vendor",
    ]
    with pytest.raises(GraphifyArgsError):
        validate_graphify_extra_args(["-c", "evil"])
    with pytest.raises(GraphifyArgsError):
        validate_graphify_extra_args(["../../etc/passwd"])
    with pytest.raises(GraphifyArgsError):
        validate_graphify_extra_args(["--unknown-flag"])
