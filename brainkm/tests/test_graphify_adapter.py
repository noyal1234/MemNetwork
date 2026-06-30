"""Tests for Graphify graph.json adapter."""

import json
from pathlib import Path

from brainkm.adapters.graphify import infer_code_subtype, load_graph_json

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "graphify_minimal.json"


def test_load_graph_json_code_only_filters_documents() -> None:
    parsed = load_graph_json(FIXTURE, code_only=True)
    node_ids = {node.graph_id for node in parsed.nodes}
    assert node_ids == {"auth", "auth_login", "models"}
    assert all(link.source in node_ids and link.target in node_ids for link in parsed.links)
    assert len(parsed.links) == 2


def test_load_graph_json_supports_edges_key() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data.pop("links")
    data["edges"] = [
        {
            "source": "auth",
            "target": "models",
            "relation": "imports_from",
            "confidence": "EXTRACTED",
        }
    ]

    path = FIXTURE.parent / "_edges_alias.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    try:
        parsed = load_graph_json(path, code_only=True)
        assert len(parsed.links) == 1
        assert parsed.links[0].relation == "imports_from"
    finally:
        path.unlink(missing_ok=True)


def test_infer_code_subtype() -> None:
    assert infer_code_subtype("auth.py", "auth") == "file"
    assert infer_code_subtype(".login()", "auth_login") == "function"
    assert infer_code_subtype("UserService", "userservice") == "class"
