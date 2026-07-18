"""Load and validate per-project BrainConfig from `.brain/config.json`."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from brainkm.config import get_settings
from brainkm.db.paths import brain_dir
from brainkm.logging_config import get_logger
from brainkm.models.brain_config import BrainConfig

logger = get_logger("services.config_loader")

CONFIG_FILENAME = "config.json"
EXAMPLE_FILENAME = "config.example.json"


def config_path(project_dir: Path | None = None) -> Path:
    return brain_dir(project_dir) / CONFIG_FILENAME


def example_config_path() -> Path:
    return Path(__file__).resolve().parents[1] / EXAMPLE_FILENAME


def load_brain_config(project_dir: Path | None = None) -> BrainConfig:
    """Load BrainConfig from disk, falling back to package defaults."""
    path = config_path(project_dir)
    if not path.is_file():
        logger.debug("No %s found; using BrainConfig defaults", path)
        return BrainConfig()

    data = json.loads(path.read_text(encoding="utf-8"))
    cfg = BrainConfig.model_validate(data)
    validate_project_roots_exist(cfg, project_dir)
    return cfg


def save_brain_config(project_dir: Path | None, config: BrainConfig) -> Path:
    """Write validated BrainConfig to ``.brain/config.json`` and clear cache."""
    path = config_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config.model_dump_json(indent=2) + "\n", encoding="utf-8")
    _cached_brain_config.cache_clear()
    return path


def validate_project_roots_exist(
    cfg: BrainConfig,
    project_dir: Path | None = None,
) -> None:
    """Warn when configured project roots are missing on disk."""
    settings = get_settings()
    root = project_dir if project_dir is not None else settings.project_dir

    for rel_root in cfg.project_roots:
        resolved = (root / rel_root).resolve()
        if not resolved.exists():
            logger.warning("project_roots entry does not exist: %s", rel_root)


def get_brain_config(project_dir: Path | None = None) -> BrainConfig:
    """Cached BrainConfig loader keyed by resolved project directory."""
    settings = get_settings()
    root = (project_dir if project_dir is not None else settings.project_dir).resolve()
    return _cached_brain_config(str(root))


@lru_cache(maxsize=8)
def _cached_brain_config(project_dir_key: str) -> BrainConfig:
    return load_brain_config(Path(project_dir_key))
