"""Typed MCP outputSchema coverage."""

from __future__ import annotations

from brainkm.server import TOOL_DEFINITIONS, _tool_schema

REQUIRED_OUTPUT_KEYS = {
    "remember": {"node_id", "title", "action"},
    "recall": {"nodes", "abstained", "query", "confidence", "decision_trail"},
    "context_pack": {"pack_text", "truncation", "query", "confidence"},
    "traverse": {
        "from_ref",
        "nodes",
        "resolved_id",
        "hint",
        "impact_summary",
        "linked_neurons",
    },
    "brain_stats": {"neurons_by_kind", "graph_nodes", "hygiene_hint"},
    "trace_changes": {"path", "pack_text", "commits", "uncommitted", "truncation"},
    "feedback": {"updated"},
    "checkpoint": {"checkpoint_ok", "neuron_count", "skipped", "reason"},
}

EXPECTED_TOOLS = {
    "remember",
    "recall",
    "context_pack",
    "traverse",
    "brain_stats",
    "trace_changes",
    "feedback",
    "checkpoint",
}


def test_tool_definitions_include_response_models() -> None:
    assert len(TOOL_DEFINITIONS) == 8
    names = {entry[0] for entry in TOOL_DEFINITIONS}
    assert names == EXPECTED_TOOLS
    for entry in TOOL_DEFINITIONS:
        assert len(entry) == 4


def test_output_schemas_include_required_keys() -> None:
    for name, _desc, _req, response_model in TOOL_DEFINITIONS:
        schema = _tool_schema(response_model)
        assert schema.get("type") == "object" or "properties" in schema
        props = schema.get("properties") or {}
        assert "additionalProperties" not in schema or props
        required = REQUIRED_OUTPUT_KEYS[name]
        assert required.issubset(set(props)), f"{name} missing {required - set(props)}"


def test_output_schema_not_stub_additional_properties_only() -> None:
    for name, _desc, _req, response_model in TOOL_DEFINITIONS:
        schema = _tool_schema(response_model)
        props = schema.get("properties") or {}
        assert props, f"{name} outputSchema has no properties"


def test_tool_descriptions_mention_when_not_to_use() -> None:
    by_name = {name: desc for name, desc, *_ in TOOL_DEFINITIONS}
    assert "Hooks" in by_name["remember"] or "hooks" in by_name["remember"].lower()
    assert "traverse" in by_name["recall"].lower() or "context_pack" in by_name["recall"]
    assert "traverse" in by_name["context_pack"]
    assert "impact" in by_name["traverse"].lower() or "blast" in by_name["traverse"].lower()
    assert "git" in by_name["trace_changes"].lower()
    assert "traverse" in by_name["trace_changes"].lower()
    assert "not a general" in by_name["feedback"].lower()
    assert "precompact" in by_name["checkpoint"].lower()
