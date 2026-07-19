"""Version discipline — pyproject.toml and package __version__ must match."""

from __future__ import annotations

import re
from pathlib import Path

import brainkm


def test_pyproject_version_matches_package() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    assert match is not None, "version missing from pyproject.toml"
    assert match.group(1) == brainkm.__version__
    assert brainkm.__version__ == "0.4.2"
