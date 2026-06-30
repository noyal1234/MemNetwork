"""Application settings for brainkm development and runtime."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Repo-level and runtime settings (env vars). Per-project brain config lives in BrainConfig."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    log_level: str = Field(default="INFO", description="Logging level for brainkm")
    project_dir: Path = Field(
        default_factory=Path.cwd,
        description="Target project root (where .brain/ lives)",
    )
    brain_dir_name: str = Field(
        default=".brain",
        description="Per-project brain storage directory name",
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached settings singleton."""
    return Settings()
