"""Tests for git-note commit joins and live change_trace."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from brainkm.db.connection import connect
from brainkm.db.migrate import migrate
from brainkm.models.brain_config import BrainConfig, GitConfig
from brainkm.models.schemas import TraceChangesRequest
from brainkm.services.change_trace import change_trace
from brainkm.services.git_note import (
    HOOK_MARKER,
    install_post_commit_hook,
    note_commit,
    uninstall_post_commit_hook,
)
from brainkm.services.memory import remember_neuron
from brainkm.services.session_activity import record_file_seed
from brainkm.tools.dispatch import handle_trace_changes
from tests.conftest import insert_node


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )


@pytest.fixture
def git_project(tmp_path: Path) -> Path:
    root = tmp_path
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    src = root / "src"
    src.mkdir()
    target = src / "widget.py"
    target.write_text("def a():\n    return 1\n", encoding="utf-8")
    _git(root, "add", "src/widget.py")
    _git(root, "commit", "-m", "add widget")
    migrate(project_dir=root, run_integrity_check=False)
    return root


def test_migration_008_indexes(brain_db: Path) -> None:
    conn = connect(brain_db)
    try:
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "idx_nodes_commit_git_hash" in indexes
        assert "idx_nodes_session_kind" in indexes
    finally:
        conn.close()


def test_git_config_commit_trace_default() -> None:
    cfg = BrainConfig()
    assert cfg.git.commit_trace is True
    cfg2 = BrainConfig(git=GitConfig(commit_trace=False))
    assert cfg2.git.commit_trace is False


def test_note_commit_and_trace_join(git_project: Path) -> None:
    root = git_project
    conn = connect(root / ".brain" / "brain.db")
    try:
        insert_node(
            conn,
            node_id="code_widget",
            kind="code",
            subtype="file",
            title="widget.py",
            path="src/widget.py",
        )
        remember_neuron(
            conn,
            title="Prefer pure widget helpers",
            content="Keep widget.py free of I/O",
            subtype="decision",
            session_id="sess-trace-1",
            source="test",
        )
        record_file_seed(conn, "sess-trace-1", "src/widget.py")
        conn.commit()

        noted = note_commit(conn, project_dir=root, session_id="sess-trace-1")
        conn.commit()
        assert noted is not None
        assert noted.created is True
        assert noted.files_linked == 1
        assert noted.neurons_linked >= 1

        # Second commit
        target = root / "src" / "widget.py"
        target.write_text("def a():\n    return 2\n", encoding="utf-8")
        _git(root, "add", "src/widget.py")
        _git(root, "commit", "-m", "bump widget return")
        noted2 = note_commit(conn, project_dir=root, session_id="sess-trace-1")
        conn.commit()
        assert noted2 is not None

        result = change_trace(
            conn,
            "src/widget.py",
            project_dir=root,
            config=BrainConfig(),
            limit=5,
            session_id="sess-trace-1",
        )
        assert len(result.commits) >= 2
        assert result.commits[0].subject == "bump widget return"
        joined = [c for c in result.commits if c.commit_node_id]
        assert joined
        assert any(c.linked_neurons for c in joined)
        assert "Change trace" in result.pack_text
        assert result.truncation.token_budget > 0
    finally:
        conn.close()


def test_trace_uncommitted_section(git_project: Path) -> None:
    root = git_project
    target = root / "src" / "widget.py"
    target.write_text("def a():\n    return 99\n", encoding="utf-8")
    conn = connect(root / ".brain" / "brain.db")
    try:
        record_file_seed(conn, "sess-live", "src/widget.py")
        conn.commit()
        result = change_trace(
            conn,
            "src/widget.py",
            project_dir=root,
            config=BrainConfig(),
            session_id="sess-live",
        )
        assert result.uncommitted.dirty is True
        assert result.uncommitted.agent_touched is True
        assert "Uncommitted" in result.pack_text
    finally:
        conn.close()


def test_note_commit_idempotent(git_project: Path) -> None:
    root = git_project
    conn = connect(root / ".brain" / "brain.db")
    try:
        first = note_commit(conn, project_dir=root)
        conn.commit()
        second = note_commit(conn, project_dir=root)
        conn.commit()
        assert first is not None and second is not None
        assert first.commit_id == second.commit_id
        assert second.created is False
        count = conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE kind='commit'"
        ).fetchone()[0]
        assert count == 1
    finally:
        conn.close()


def test_install_post_commit_hook(git_project: Path) -> None:
    result = install_post_commit_hook(git_project, brainkm_bin="brainkm")
    assert result.installed is True
    assert result.path is not None
    assert result.path.is_file()
    text = result.path.read_text(encoding="utf-8")
    assert HOOK_MARKER in text
    assert "command -v brainkm" in text
    assert "git-note" in text
    # Reinstall merges, does not duplicate forever
    install_post_commit_hook(git_project, brainkm_bin="brainkm")
    text2 = result.path.read_text(encoding="utf-8")
    assert text2.count(HOOK_MARKER) == 1
    assert uninstall_post_commit_hook(git_project) is True


def test_handle_trace_changes_mcp(git_project: Path) -> None:
    conn = connect(git_project / ".brain" / "brain.db")
    try:
        response = handle_trace_changes(
            conn,
            TraceChangesRequest(path="src/widget.py", limit=5),
            config=BrainConfig(),
            project_dir=git_project,
        )
        assert response.path == "src/widget.py"
        assert response.pack_text
        assert len(response.commits) >= 1
    finally:
        conn.close()


def test_install_writes_hook_when_commit_trace(tmp_path: Path) -> None:
    from brainkm.services.install import run_install

    _git(tmp_path, "init")
    # Explicit True still works; default is also True for BrainConfig().
    cfg = BrainConfig(git=GitConfig(commit_trace=True))
    result = run_install(
        project_dir=tmp_path,
        dev=True,
        no_graph=True,
        force=True,
        config=cfg,
    )
    hook_written = any(p.name == "post-commit" for p in result.files_written)
    assert hook_written
    hook = tmp_path / ".git" / "hooks" / "post-commit"
    assert hook.is_file()
    assert HOOK_MARKER in hook.read_text(encoding="utf-8")


def test_install_writes_hook_by_default(tmp_path: Path) -> None:
    from brainkm.services.install import run_install

    _git(tmp_path, "init")
    result = run_install(
        project_dir=tmp_path,
        dev=True,
        no_graph=True,
        force=True,
        config=BrainConfig(),
    )
    assert any(p.name == "post-commit" for p in result.files_written)


def test_grandfather_missing_commit_trace_skips_hook(tmp_path: Path) -> None:
    import json

    from brainkm.services.config_loader import (
        raw_config_has_commit_trace,
        should_install_commit_hook,
    )
    from brainkm.services.install import run_install

    _git(tmp_path, "init")
    brain = tmp_path / ".brain"
    brain.mkdir(parents=True)
    # Existing config without commit_trace key
    (brain / "config.json").write_text(
        json.dumps({"git": {"enabled": False, "link_on_capture": True}}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    assert raw_config_has_commit_trace(tmp_path) is False
    assert should_install_commit_hook(tmp_path) is False

    result = run_install(
        project_dir=tmp_path,
        dev=True,
        no_graph=True,
        force=False,
        config=None,
    )
    assert not any(p.name == "post-commit" for p in result.files_written)
    saved = json.loads((brain / "config.json").read_text(encoding="utf-8"))
    assert saved["git"]["commit_trace"] is False
    assert any("grandfather" in w.lower() or "unset" in w.lower() for w in result.warnings)


def test_hook_skips_when_husky_present(git_project: Path) -> None:
    (git_project / ".husky").mkdir()
    result = install_post_commit_hook(git_project, brainkm_bin="brainkm")
    assert result.skipped is True
    assert result.installed is False
    assert any(".husky" in w for w in result.warnings)


def test_hook_warns_when_appending_to_foreign_post_commit(git_project: Path) -> None:
    hooks = git_project / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    foreign = hooks / "post-commit"
    foreign.write_text("#!/bin/sh\necho foreign\n", encoding="utf-8")
    foreign.chmod(0o755)
    result = install_post_commit_hook(git_project, brainkm_bin="brainkm")
    assert result.installed is True
    assert result.appended_to_existing is True
    text = foreign.read_text(encoding="utf-8")
    assert "foreign" in text
    assert HOOK_MARKER in text


def test_note_commit_skips_merge(git_project: Path) -> None:
    root = git_project
    base = _git(root, "branch", "--show-current").stdout.strip() or "main"
    _git(root, "checkout", "-b", "feature")
    (root / "src" / "widget.py").write_text("def a():\n    return 3\n", encoding="utf-8")
    _git(root, "add", "src/widget.py")
    _git(root, "commit", "-m", "feature change")
    _git(root, "checkout", base)
    _git(root, "merge", "--no-ff", "feature", "-m", "merge feature")
    conn = connect(root / ".brain" / "brain.db")
    try:
        noted = note_commit(conn, project_dir=root)
        conn.commit()
        assert noted is not None
        assert noted.skipped is True
        assert noted.skip_reason == "merge"
    finally:
        conn.close()


def test_archive_expired_commits(brain_db: Path) -> None:
    from datetime import UTC, datetime, timedelta

    from brainkm.services.hygiene import archive_expired_commits
    from brainkm.services.memory import create_neuron

    conn = connect(brain_db)
    try:
        old = create_neuron(
            conn,
            title="old commit",
            content="files: none",
            kind="commit",
            subtype="git",
            source="test",
        )
        old_ts = (datetime.now(UTC) - timedelta(days=120)).isoformat()
        conn.execute(
            "UPDATE nodes SET created_at = ?, git_hash = ? WHERE id = ?",
            (old_ts, "abc123", old.id),
        )
        recent = create_neuron(
            conn,
            title="recent commit",
            content="files: x",
            kind="commit",
            subtype="git",
            source="test",
        )
        conn.execute(
            "UPDATE nodes SET git_hash = ? WHERE id = ?",
            ("def456", recent.id),
        )
        conn.commit()
        archived = archive_expired_commits(conn, retention_days=90, dry_run=False)
        conn.commit()
        assert old.id in archived
        assert recent.id not in archived
        row = conn.execute(
            "SELECT valid_until FROM nodes WHERE id = ?", (old.id,)
        ).fetchone()
        assert row[0] is not None
    finally:
        conn.close()


def test_config_form_includes_git_section() -> None:
    from brainkm.tui.widgets.config_form import SECTION_FIELDS

    assert "git" in SECTION_FIELDS
    keys = {f["key"] for f in SECTION_FIELDS["git"]}
    assert "commit_trace" in keys
    assert "commit_retention_days" in keys


def test_should_install_fresh_defaults_true(tmp_path: Path) -> None:
    from brainkm.services.config_loader import should_install_commit_hook

    assert should_install_commit_hook(tmp_path, BrainConfig()) is True
    assert should_install_commit_hook(
        tmp_path, BrainConfig(git=GitConfig(commit_trace=False))
    ) is False
