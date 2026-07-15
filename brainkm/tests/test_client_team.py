"""Tests for client adapters and team layer."""

from __future__ import annotations

from pathlib import Path

from brainkm.services.client_adapters import get_client_adapter
from brainkm.services.install import run_install
from brainkm.services.team import export_team_neurons, import_team_neurons
from brainkm.db.connection import connect
from brainkm.db.migrate import migrate
from brainkm.services.memory import remember_neuron


def test_client_adapters() -> None:
    cursor = get_client_adapter("cursor")
    claude = get_client_adapter("claude")
    generic = get_client_adapter("generic")
    assert "sessionStart" in cursor.hook_events()
    assert "postCompact" in claude.hook_events()
    assert generic.hook_events() == []
    assert "recall" in generic.agents_snippet()


def test_install_generic_writes_agents(tmp_path: Path) -> None:
    result = run_install(project_dir=tmp_path, dev=True, no_graph=True, client="generic")
    assert (tmp_path / "AGENTS.md").is_file() or any(
        p.name == "AGENTS.md" for p in result.files_written
    )


def test_team_export_import(tmp_path: Path) -> None:
    migrate(project_dir=tmp_path, run_integrity_check=False)
    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        remember_neuron(
            conn,
            title="Team decision JWT",
            content="Team chose JWT for shared APIs.",
            subtype="decision",
            confidence=0.95,
        )
        conn.execute("UPDATE nodes SET user_pinned = 1 WHERE title LIKE 'Team%'")
        conn.commit()
    finally:
        conn.close()

    path = export_team_neurons(tmp_path)
    assert path.is_file()

    other = tmp_path / "other"
    other.mkdir()
    migrate(project_dir=other, run_integrity_check=False)
    # copy team file
    team_src = tmp_path / ".brain" / "team" / "neurons.json"
    dest = other / ".brain" / "team"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "neurons.json").write_text(team_src.read_text(encoding="utf-8"), encoding="utf-8")
    imported = import_team_neurons(other)
    assert imported >= 1
