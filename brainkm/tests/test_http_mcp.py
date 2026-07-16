"""HTTP MCP create_server smoke (transport wiring covered separately)."""

from __future__ import annotations

from pathlib import Path

from brainkm.db.migrate import migrate
from brainkm.server import create_server
from brainkm.tools.dispatch import BrainRuntime


def test_create_server_for_http_path(tmp_path: Path) -> None:
    migrate(project_dir=tmp_path, run_integrity_check=False)
    server = create_server(BrainRuntime(project_dir=tmp_path))
    assert server.name == "brainkm"
