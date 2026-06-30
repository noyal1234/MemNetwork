"""Tests for context_pack compiler."""

from brainkm.db.connection import connect
from brainkm.models.brain_config import BrainConfig
from brainkm.services.context_pack import compile_context_pack, derive_pre_tool_query
from tests.conftest import insert_node


def test_derive_pre_tool_query_from_path() -> None:
    query = derive_pre_tool_query({"tool_input": {"path": "src/auth/middleware.py"}})
    assert query == "src/auth/middleware.py"


def test_derive_pre_tool_query_returns_none_for_empty() -> None:
    assert derive_pre_tool_query({"tool_name": "Shell"}) is None
    assert derive_pre_tool_query({}) is None


def test_compile_context_pack_includes_neuron(brain_db) -> None:
    conn = connect(brain_db)
    try:
        insert_node(
            conn,
            node_id="jwt",
            subtype="decision",
            title="JWT expiry policy",
            content="Use 15 minute access tokens",
        )
        conn.commit()

        pack = compile_context_pack(
            conn,
            "JWT expiry",
            config=BrainConfig(recall={"abstain_on_low_confidence": False}),
        )
        assert "JWT expiry policy" in pack.pack_text
        assert any(n.node_id == "jwt" for n in pack.neurons)
        assert pack.truncation.tokens_used > 0
    finally:
        conn.close()
