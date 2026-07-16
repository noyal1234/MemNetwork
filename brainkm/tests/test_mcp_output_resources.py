"""Typed MCP outputSchema coverage."""

from __future__ import annotations

from brainkm.server import TOOL_DEFINITIONS, _tool_schema


REQUIRED_OUTPUT_KEYS = {
    "remember": {"node_id", "title"},
    "recall": {"nodes", "abstained", "query"},
    "context_pack": {"pack_text", "truncation", "query"},
    "session_status": {"updated"},
    "traverse": {"from_ref", "nodes"},
    "forget": {"node_id", "archived"},
    "brain_stats": {"neurons_by_kind", "graph_nodes"},
    "graph_sync": {"requested", "ran"},
}


def test_tool_definitions_include_response_models() -> None:
    assert len(TOOL_DEFINITIONS) == 8
    for entry in TOOL_DEFINITIONS:
        assert len(entry) == 4


def test_output_schemas_include_required_keys() -> None:
    for name, _desc, _req, response_model in TOOL_DEFINITIONS:
        schema = _tool_schema(response_model)
        assert schema.get("type") == "object" or "properties" in schema
        props = schema.get("properties") or {}
        # Strip stub-only schemas
        assert "additionalProperties" not in schema or props
        required = REQUIRED_OUTPUT_KEYS[name]
        assert required.issubset(set(props)), f"{name} missing {required - set(props)}"


def test_output_schema_not_stub_additional_properties_only() -> None:
    for name, _desc, _req, response_model in TOOL_DEFINITIONS:
        schema = _tool_schema(response_model)
        props = schema.get("properties") or {}
        assert props, f"{name} outputSchema has no properties"
