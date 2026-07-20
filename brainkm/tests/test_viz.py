"""Tests for brainkm viz server helpers used by CLI and TUI."""

from __future__ import annotations

import json
import sqlite3
from importlib import resources
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

import pytest

from brainkm.services import viz as viz_mod
from brainkm.services.viz import start_viz_server


def _api(handle, path: str) -> str:
    """Build an authenticated API URL from VizServerHandle fields."""
    sep = "&" if "?" in path else "?"
    return f"{handle.base_url}{path}{sep}token={handle.token}"


def test_viz_static_package_data_includes_ui_assets() -> None:
    """Wheel / installable package must ship viz_static assets (not just source tree)."""
    root = resources.files("brainkm") / "services" / "viz_static"
    assert (root / "index.html").is_file()
    assert (root / "styles.css").is_file()
    assert (root / "app.js").is_file()
    assert (root / "chat.js").is_file()
    assert (root / "webllm-worker.js").is_file()


def test_start_viz_server_demo_serves_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("webbrowser.open", lambda *_a, **_k: True)
    handle = start_viz_server(demo=True, open_browser=False, port=0)
    try:
        with urlopen(_api(handle, "/api/graph"), timeout=2) as resp:  # noqa: S310
            body = json.loads(resp.read().decode())
        assert len(body["nodes"]) > 0
        assert len(body["edges"]) > 0
        # path/source included in payload
        code = next(n for n in body["nodes"] if n["kind"] == "code")
        assert code.get("path")
        assert handle.node_count > 0
    finally:
        handle.stop()


def test_demo_serves_static_assets_and_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("webbrowser.open", lambda *_a, **_k: True)
    handle = start_viz_server(demo=True, open_browser=False, port=0)
    try:
        with urlopen(f"{handle.base_url}/?token={handle.token}", timeout=2) as resp:  # noqa: S310
            html = resp.read().decode()
        assert "Neural Cosmos" in html
        assert "/app.js" in html

        with urlopen(f"{handle.base_url}/styles.css", timeout=2) as resp:  # noqa: S310
            assert resp.status == 200
            assert b"--bg" in resp.read()

        with urlopen(f"{handle.base_url}/app.js", timeout=2) as resp:  # noqa: S310
            assert b"createChatController" in resp.read()

        with urlopen(_api(handle, "/api/version"), timeout=2) as resp:  # noqa: S310
            ver = json.loads(resp.read().decode())
        assert ver["node_count"] == handle.node_count
        assert ver["edge_count"] == handle.edge_count
        assert "max_updated" in ver
    finally:
        handle.stop()


def test_demo_search_returns_fts_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("webbrowser.open", lambda *_a, **_k: True)
    handle = start_viz_server(demo=True, open_browser=False, port=0)
    try:
        q = quote("SQLite")
        with urlopen(_api(handle, f"/api/search?q={q}&limit=5"), timeout=2) as resp:  # noqa: S310
            data = json.loads(resp.read().decode())
        assert data["query"] == "SQLite"
        assert isinstance(data["results"], list)
        assert len(data["results"]) >= 1
        assert "title" in data["results"][0]
        assert "id" in data["results"][0]
    finally:
        handle.stop()


def test_live_graph_reflects_writes_after_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-request DB query — nodes inserted after server start appear in /api/graph."""
    from brainkm.db.connection import configure_connection
    from brainkm.db.paths import brain_db_path, migrations_dir

    brain_dir = tmp_path / ".brain"
    brain_dir.mkdir()
    db_path = brain_db_path(tmp_path)
    conn = sqlite3.connect(str(db_path))
    configure_connection(conn)
    for sql_path in sorted(migrations_dir().glob("*.sql")):
        conn.executescript(sql_path.read_text(encoding="utf-8"))
    conn.execute(
        """INSERT INTO nodes
           (id, kind, subtype, title, content, tags, use_count, confidence,
            user_pinned, valid_from, valid_until, ingested_at, session_id,
            created_at, updated_at, path, source)
           VALUES ('n1','memory','fact','Before start','content','t',1,1.0,
                   0,'2025-01-01',NULL,'2025-01-01',NULL,
                   '2025-01-01','2025-01-01',NULL,'test')"""
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr("webbrowser.open", lambda *_a, **_k: True)
    handle = start_viz_server(project_dir=tmp_path, demo=False, open_browser=False, port=0)
    try:
        with urlopen(_api(handle, "/api/graph"), timeout=2) as resp:  # noqa: S310
            before = json.loads(resp.read().decode())
        assert any(n["id"] == "n1" for n in before["nodes"])
        assert not any(n["id"] == "n2" for n in before["nodes"])

        # Write after server start
        conn = sqlite3.connect(str(db_path))
        configure_connection(conn)
        conn.execute(
            """INSERT INTO nodes
               (id, kind, subtype, title, content, tags, use_count, confidence,
                user_pinned, valid_from, valid_until, ingested_at, session_id,
                created_at, updated_at, path, source)
               VALUES ('n2','memory','fact','After start','live content','live',1,1.0,
                       0,'2025-01-02',NULL,'2025-01-02',NULL,
                       '2025-01-02','2025-01-02',NULL,'test')"""
        )
        conn.commit()
        conn.close()

        with urlopen(_api(handle, "/api/graph"), timeout=2) as resp:  # noqa: S310
            after = json.loads(resp.read().decode())
        assert any(n["id"] == "n2" for n in after["nodes"])

        with urlopen(_api(handle, "/api/version"), timeout=2) as resp:  # noqa: S310
            ver = json.loads(resp.read().decode())
        assert ver["node_count"] == 2
    finally:
        handle.stop()


def test_start_viz_server_requires_brain_db(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="No brain.db"):
        start_viz_server(project_dir=tmp_path, demo=False, open_browser=False)


def test_query_graph_includes_path_and_archived() -> None:
    from brainkm.db.connection import configure_connection
    from brainkm.db.paths import migrations_dir

    conn = sqlite3.connect(":memory:")
    configure_connection(conn)
    for sql_path in sorted(migrations_dir().glob("*.sql")):
        conn.executescript(sql_path.read_text(encoding="utf-8"))
    viz_mod._seed_demo(conn)
    data = viz_mod._query_graph(conn)
    assert any(n.get("path") for n in data["nodes"] if n["kind"] == "code")
    assert any(n.get("valid_until") for n in data["nodes"])
    conn.close()
