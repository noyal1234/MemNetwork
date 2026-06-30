"""Resolve per-project brain storage paths."""

from pathlib import Path

from brainkm.config import get_settings


def brain_dir(project_dir: Path | None = None) -> Path:
    settings = get_settings()
    root = project_dir if project_dir is not None else settings.project_dir
    return root / settings.brain_dir_name


def brain_db_path(project_dir: Path | None = None) -> Path:
    return brain_dir(project_dir) / "brain.db"


def migrations_dir() -> Path:
    return Path(__file__).resolve().parent / "migrations"
