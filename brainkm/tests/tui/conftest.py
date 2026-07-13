"""Shared fixtures for TUI tests — an isolated, fully-scaffolded project dir."""

from __future__ import annotations

from pathlib import Path

import pytest

from brainkm.db.migrate import migrate


@pytest.fixture
def tui_project(tmp_path: Path) -> Path:
    """A temp project dir with a migrated brain.db and a default config.json.

    Using this fixture (instead of the real repo cwd) is required for every
    TUI test: `BrainkmConfigureApp` and its screens must never touch the
    developer's actual `.brain/` directory.
    """
    brain_dir = tmp_path / ".brain"
    brain_dir.mkdir(parents=True, exist_ok=True)
    migrate(db_path=brain_dir / "brain.db", run_integrity_check=True)
    (brain_dir / "config.json").write_text("{}\n", encoding="utf-8")
    return tmp_path
