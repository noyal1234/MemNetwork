"""Tests for context_pack compiler."""

from brainkm.db.connection import connect
from brainkm.models.brain_config import BrainConfig
from brainkm.services.context_pack import (
    GRAPH_HINT,
    compile_context_pack,
    compile_pre_tool_pack,
    derive_pre_tool_query,
    extract_seed_candidates,
)
from tests.conftest import insert_edge, insert_node


def _mark_graph_imported(conn) -> None:
    conn.execute(
        """
        INSERT INTO graph_import_runs (id, started_at, completed_at, status, node_count, edge_count)
        VALUES ('run1', '2026-01-01T00:00:00Z', '2026-01-01T00:00:01Z', 'completed', 2, 1)
        """
    )


def test_derive_pre_tool_query_from_path() -> None:
    query = derive_pre_tool_query({"tool_input": {"path": "src/auth/middleware.py"}})
    assert query == "src/auth/middleware.py"


def test_derive_pre_tool_query_returns_none_for_empty() -> None:
    assert derive_pre_tool_query({"tool_name": "Shell"}) is None
    assert derive_pre_tool_query({}) is None


def test_derive_pre_tool_query_skips_plain_shell_noise() -> None:
    assert derive_pre_tool_query({"tool_input": {"command": "wc -l"}}) is None
    assert derive_pre_tool_query({"tool_input": {"command": "grep -n foo"}}) is None
    assert (
        derive_pre_tool_query(
            {"tool_input": {"command": "open Screenshot_2026-07-27_at_6.10.30_PM.png"}}
        )
        is None
    )


def test_derive_pre_tool_query_shell_keeps_source_path_or_symbol() -> None:
    assert (
        derive_pre_tool_query(
            {"tool_input": {"command": "pytest brainkm/tests/test_hooks.py -q"}}
        )
        is not None
    )
    seed = derive_pre_tool_query(
        {"tool_input": {"command": "rg -n remember_neuron brainkm/"}}
    )
    assert seed is not None
    assert "remember_neuron" in seed or "brainkm" in seed


def test_extract_seed_candidates_paths_symbols_and_stopwords() -> None:
    cands = extract_seed_candidates(
        "How does AuthService connect to user_repo in services/auth.py?"
    )
    assert "services/auth.py" in cands
    assert "AuthService" in cands
    assert "user_repo" in cands
    assert "How" not in cands
    assert "does" not in cands


def test_extract_seed_candidates_includes_markdown_paths() -> None:
    cands = extract_seed_candidates("edit docs/install/codex.md trust gate")
    assert "docs/install/codex.md" in cands
    assert "codex" in cands


def test_path_stem_tokens_from_docs_path() -> None:
    from brainkm.services.context_pack import path_stem_tokens

    assert path_stem_tokens("docs/install/codex.md") == ["install", "codex"]
    assert path_stem_tokens("brainkm/brainkm/services/context_pack.py") == [
        "brainkm",
        "services",
        "context",
        "pack",
    ]


def test_extract_seed_candidates_respects_explicit() -> None:
    cands = extract_seed_candidates("random chatter", explicit=["CompileContextPack"])
    assert cands[0] == "CompileContextPack"


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
            include_structured=True,
        )
        assert "JWT expiry policy" in pack.pack_text
        assert any(n.node_id == "jwt" for n in pack.neurons)
        assert pack.truncation.tokens_used > 0
    finally:
        conn.close()


def test_compile_context_pack_blocks_redaction_flagged_neuron(brain_db) -> None:
    """Outbound gate: legacy rows with secrets never reach agent-facing packs."""
    conn = connect(brain_db)
    try:
        insert_node(
            conn,
            node_id="jwt-clean",
            subtype="decision",
            title="JWT expiry policy",
            content="Use 15 minute access tokens",
        )
        # Direct INSERT bypasses remember_neuron — simulates a row stored
        # before the matching redaction rule existed.
        insert_node(
            conn,
            node_id="jwt-leak",
            subtype="decision",
            title="JWT expiry signing key",
            content="Sign JWT expiry tokens with sk-live-abcdefghijklmnopqrstuvwxyz123456",
        )
        conn.commit()

        pack = compile_context_pack(
            conn,
            "JWT expiry",
            config=BrainConfig(recall={"abstain_on_low_confidence": False}),
            include_structured=True,
        )
        assert any(n.node_id == "jwt-clean" for n in pack.neurons)
        assert all(n.node_id != "jwt-leak" for n in pack.neurons)
        assert "sk-live-" not in pack.pack_text
    finally:
        conn.close()


def test_compile_context_pack_seeds_symbol_neighborhood(brain_db) -> None:
    conn = connect(brain_db)
    try:
        _mark_graph_imported(conn)
        insert_node(
            conn,
            node_id="auth-file",
            kind="code",
            subtype="file",
            title="auth.py",
            path="services/auth.py",
            content="Auth module",
        )
        insert_node(
            conn,
            node_id="AuthService",
            kind="code",
            subtype="class",
            title="AuthService",
            path="services/auth.py",
            content="class AuthService",
        )
        insert_node(
            conn,
            node_id="user-repo",
            kind="code",
            subtype="class",
            title="UserRepo",
            path="services/user.py",
            content="class UserRepo",
        )
        insert_edge(
            conn,
            edge_id="e1",
            from_id="AuthService",
            to_id="user-repo",
            relationship="calls",
        )
        conn.commit()

        pack = compile_context_pack(
            conn,
            "What connects AuthService to the repo?",
            config=BrainConfig(recall={"abstain_on_low_confidence": False}),
            include_structured=True,
        )
        assert pack.graph_available is True
        assert pack.graph_hint is None
        assert any(n.node_id == "AuthService" for n in pack.graph_nodes)
        assert "Code neighborhood" in pack.pack_text
    finally:
        conn.close()


def test_compile_context_pack_seed_refs_param(brain_db) -> None:
    conn = connect(brain_db)
    try:
        _mark_graph_imported(conn)
        insert_node(
            conn,
            node_id="cfg",
            kind="code",
            subtype="file",
            title="config.py",
            path="brainkm/config.py",
        )
        insert_node(
            conn,
            node_id="loader",
            kind="code",
            subtype="function",
            title="load_brain_config",
            path="brainkm/services/config_loader.py",
        )
        insert_edge(
            conn,
            edge_id="e1",
            from_id="loader",
            to_id="cfg",
            relationship="imports",
        )
        conn.commit()

        pack = compile_context_pack(
            conn,
            "need neighborhood for refactor",
            config=BrainConfig(recall={"abstain_on_low_confidence": False}),
            seed_refs=["load_brain_config"],
            include_structured=True,
        )
        assert any(n.node_id in {"loader", "cfg"} for n in pack.graph_nodes)
    finally:
        conn.close()


def test_compile_context_pack_graph_hint_on_unresolvable_query(brain_db) -> None:
    conn = connect(brain_db)
    try:
        _mark_graph_imported(conn)
        insert_node(
            conn,
            node_id="lonely",
            kind="code",
            subtype="file",
            title="zzz_unique_file.py",
            path="zzz_unique_file.py",
        )
        conn.commit()

        pack = compile_context_pack(
            conn,
            "How does this totally unrelated phrase work?",
            config=BrainConfig(recall={"abstain_on_low_confidence": False}),
        )
        assert pack.graph_available is True
        assert pack.graph_hint == GRAPH_HINT
        assert GRAPH_HINT in pack.pack_text
    finally:
        conn.close()


def test_per_channel_budget_reserves_graph_slot(brain_db) -> None:
    conn = connect(brain_db)
    try:
        _mark_graph_imported(conn)
        # Large neuron that would starve code under a single shared greedy pool.
        insert_node(
            conn,
            node_id="big-decision",
            subtype="decision",
            title="AuthService architecture decision",
            content="x " * 400,
        )
        insert_node(
            conn,
            node_id="AuthService",
            kind="code",
            subtype="class",
            title="AuthService",
            path="auth.py",
            content="class AuthService for middleware",
        )
        insert_node(
            conn,
            node_id="helper",
            kind="code",
            subtype="function",
            title="validate_token",
            path="auth.py",
            content="def validate_token",
        )
        insert_edge(
            conn,
            edge_id="e1",
            from_id="AuthService",
            to_id="helper",
            relationship="calls",
        )
        conn.commit()

        pack = compile_context_pack(
            conn,
            "auth.py AuthService refactor flow",
            config=BrainConfig(
                budget={"total_tokens": 600, "dynamic_reallocation": True},
                recall={"abstain_on_low_confidence": False},
            ),
            include_structured=True,
        )
        assert pack.graph_nodes, "graph channel must retain code neighborhood under budget"
        assert any(n.kind == "code" for n in pack.graph_nodes)
    finally:
        conn.close()


def test_compile_pre_tool_pack_uses_file_path_and_slot_cap(brain_db) -> None:
    conn = connect(brain_db)
    try:
        _mark_graph_imported(conn)
        insert_node(
            conn,
            node_id="auth-file",
            kind="code",
            subtype="file",
            title="middleware.py",
            path="src/auth/middleware.py",
            content="auth middleware file",
        )
        insert_node(
            conn,
            node_id="caller",
            kind="code",
            subtype="function",
            title="handle_request",
            path="src/app.py",
            content="calls middleware",
        )
        insert_edge(
            conn,
            edge_id="e1",
            from_id="caller",
            to_id="auth-file",
            relationship="imports",
        )
        conn.commit()

        config = BrainConfig(
            budget={
                "total_tokens": 1500,
                "pre_tool": {"graph_neighborhood": 400, "procedure_expanded": 250},
            },
            recall={"abstain_on_low_confidence": False},
        )
        pack = compile_pre_tool_pack(
            conn,
            {"tool_name": "Write", "tool_input": {"path": "src/auth/middleware.py"}},
            config=config,
        )
        assert pack is not None
        assert pack.truncation.token_budget <= 400 + 250 + 200
        assert (
            any(nid in {"auth-file", "caller"} for nid in pack.truncation.included_ids)
            or "middleware" in pack.pack_text.lower()
        )
    finally:
        conn.close()
