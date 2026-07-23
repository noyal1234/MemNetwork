"""Tests for Graphify filesystem watch (multi-IDE auto-sync)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from brainkm.models.brain_config import BrainConfig, GraphifyAutoSyncConfig
from brainkm.services.graphify_sync import (
    GraphSyncScheduler,
    build_graph_status,
    request_graph_sync,
)
from brainkm.services.graphify_watch import (
    GraphifyFilesystemWatch,
    should_request_sync,
)


def test_should_ignore_brain_and_graphify_out(tmp_path: Path) -> None:
    root = tmp_path
    (root / ".brain").mkdir()
    (root / "graphify-out").mkdir()
    assert should_request_sync(root / ".brain" / "brain.db", root) is False
    assert should_request_sync(root / "graphify-out" / "graph.json", root) is False


def test_should_ignore_git_and_node_modules(tmp_path: Path) -> None:
    root = tmp_path
    nested = root / "pkg" / "node_modules" / "x"
    nested.mkdir(parents=True)
    assert should_request_sync(nested / "index.js", root) is False
    assert should_request_sync(root / ".git" / "HEAD", root) is False


def test_should_allow_source_py(tmp_path: Path) -> None:
    root = tmp_path
    src = root / "src"
    src.mkdir()
    path = src / "foo.py"
    path.write_text("x = 1\n", encoding="utf-8")
    assert should_request_sync(path, root) is True


def test_should_ignore_markdown_extension(tmp_path: Path) -> None:
    root = tmp_path
    path = root / "README.md"
    path.write_text("# hi\n", encoding="utf-8")
    assert should_request_sync(path, root) is False


def test_honors_graphifyignore_docs(tmp_path: Path) -> None:
    root = tmp_path
    (root / ".graphifyignore").write_text("docs/\n", encoding="utf-8")
    docs = root / "docs"
    docs.mkdir()
    path = docs / "a.py"
    path.write_text("pass\n", encoding="utf-8")
    assert should_request_sync(path, root) is False


def test_watch_notify_creates_request_flag(tmp_path: Path) -> None:
    root = tmp_path
    (root / ".brain").mkdir()
    src = root / "app.py"
    src.write_text("pass\n", encoding="utf-8")
    watch = GraphifyFilesystemWatch(root, config=BrainConfig())
    watch._maybe_request(src)
    assert (root / ".brain" / "graph_sync.requested").is_file()


def test_watch_start_stop_with_mocked_observer(tmp_path: Path) -> None:
    root = tmp_path
    (root / "src").mkdir()
    mock_observer = MagicMock()
    mock_observer.is_alive.return_value = True

    with patch("watchdog.observers.Observer", return_value=mock_observer):
        with patch("watchdog.events.FileSystemEventHandler"):
            watch = GraphifyFilesystemWatch(
                root,
                config=BrainConfig(project_roots=["src"]),
            )
            watch.start()
            assert mock_observer.schedule.called
            assert mock_observer.start.called
            assert watch.is_active is True
            watch.stop()
            mock_observer.stop.assert_called_once()
            mock_observer.join.assert_called_once()


def test_scheduler_starts_watch_when_enabled(tmp_path: Path) -> None:
    (tmp_path / ".brain").mkdir()
    config = BrainConfig(
        graphify={
            "auto_sync": GraphifyAutoSyncConfig(
                enabled=True,
                watch_filesystem=True,
                debounce_seconds=60.0,
                min_interval_seconds=300.0,
            )
        }
    )
    mock_watch = MagicMock()
    with patch(
        "brainkm.services.graphify_watch.GraphifyFilesystemWatch",
        return_value=mock_watch,
    ):
        # Avoid startup sync side effects
        with patch.object(GraphSyncScheduler, "_maybe_schedule_startup_sync"):
            scheduler = GraphSyncScheduler(tmp_path, config)
            scheduler.start()
            mock_watch.start.assert_called_once()
            scheduler.stop(timeout=1.0)
            mock_watch.stop.assert_called_once()


def test_scheduler_skips_watch_by_default(tmp_path: Path) -> None:
    (tmp_path / ".brain").mkdir()
    config = BrainConfig()
    assert config.graphify.auto_sync.watch_filesystem is False
    with patch("brainkm.services.graphify_watch.GraphifyFilesystemWatch") as mock_cls:
        with patch.object(GraphSyncScheduler, "_maybe_schedule_startup_sync"):
            scheduler = GraphSyncScheduler(tmp_path, config)
            scheduler.start()
            mock_cls.assert_not_called()
            scheduler.stop(timeout=1.0)


def test_build_graph_status_includes_watch_flag(tmp_path: Path) -> None:
    status = build_graph_status(tmp_path, BrainConfig())
    assert status["watch_filesystem_enabled"] is False
    status_on = build_graph_status(
        tmp_path,
        BrainConfig(graphify={"auto_sync": {"watch_filesystem": True}}),
    )
    assert status_on["watch_filesystem_enabled"] is True


def test_request_graph_sync_still_works(tmp_path: Path) -> None:
    request_graph_sync(tmp_path)
    assert (tmp_path / ".brain" / "graph_sync.requested").is_file()
