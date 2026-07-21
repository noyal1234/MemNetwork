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
    groq_api_key: str | None = Field(
        default=None,
        description="Groq API key for cloud distill (env: GROQ_API_KEY)",
    )
    brainkm_skip_rolling_scores: bool = Field(
        default=False,
        description=(
            "When true, skip appending BM25 scores to the abstention rolling window "
            "(env: BRAINKM_SKIP_ROLLING_SCORES=1). Used by bench harnesses."
        ),
        validation_alias="BRAINKM_SKIP_ROLLING_SCORES",
    )
    longmemeval_path: Path | None = Field(
        default=None,
        description=(
            "Optional path to LongMemEval-S cleaned JSON for the retrieval footnote suite "
            "(env: LONGMEMEVAL_PATH)."
        ),
        validation_alias="LONGMEMEVAL_PATH",
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached settings singleton."""
    return Settings()


def apply_project_env(project_dir: Path | None) -> Path | None:
    """Load ``{project_dir}/.env`` into the process and refresh settings.

    Antigravity (and some other hosts) run hooks with ``cwd`` set to a nested
    customization dir (e.g. ``.agents/``). Pydantic's default ``env_file=".env"``
    is cwd-relative, so ``GROQ_API_KEY`` in the project ``.env`` would be missed
    and Groq distill would silently fall back to rules. Call this after resolving
    the real project root.
    """
    if project_dir is None:
        return None
    root = project_dir.expanduser().resolve()
    env_path = root / ".env"
    if not env_path.is_file():
        return None
    try:
        from dotenv import load_dotenv
    except ImportError:
        return None
    # Do not override vars already set in the real environment.
    load_dotenv(env_path, override=False)
    get_settings.cache_clear()
    return env_path


def set_skip_rolling_scores(enabled: bool) -> None:
    """Toggle BRAINKM_SKIP_ROLLING_SCORES and clear the settings cache."""
    import os

    if enabled:
        os.environ["BRAINKM_SKIP_ROLLING_SCORES"] = "1"
    else:
        os.environ.pop("BRAINKM_SKIP_ROLLING_SCORES", None)
    get_settings.cache_clear()
