"""Tests for brainkm viz server helpers used by CLI and TUI."""

from __future__ import annotations

from pathlib import Path
from urllib.request import urlopen

import pytest

from brainkm.services.viz import start_viz_server


def test_start_viz_server_demo_serves_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("webbrowser.open", lambda *_a, **_k: True)
    handle = start_viz_server(demo=True, open_browser=False, port=0)
    try:
        with urlopen(f"{handle.url}/api/graph", timeout=2) as resp:  # noqa: S310
            body = resp.read().decode()
        assert '"nodes"' in body
        assert handle.node_count > 0
    finally:
        handle.stop()


def test_start_viz_server_requires_brain_db(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="No brain.db"):
        start_viz_server(project_dir=tmp_path, demo=False, open_browser=False)
