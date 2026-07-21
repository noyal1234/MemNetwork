"""Project .env loading for hooks that run with a nested cwd (e.g. .agents)."""

from __future__ import annotations

import os
from pathlib import Path

from brainkm.config import apply_project_env, get_settings


def test_apply_project_env_loads_groq_key_when_cwd_is_nested(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    nested = project / ".agents"
    nested.mkdir(parents=True)
    (project / ".env").write_text("GROQ_API_KEY=gsk_test_from_project_env\n", encoding="utf-8")

    os.environ.pop("GROQ_API_KEY", None)
    get_settings.cache_clear()
    old = Path.cwd()
    try:
        os.chdir(nested)
        get_settings.cache_clear()
        assert get_settings().groq_api_key is None
        loaded = apply_project_env(project)
        assert loaded == (project / ".env").resolve()
        assert get_settings().groq_api_key == "gsk_test_from_project_env"
    finally:
        os.chdir(old)
        os.environ.pop("GROQ_API_KEY", None)
        get_settings.cache_clear()
