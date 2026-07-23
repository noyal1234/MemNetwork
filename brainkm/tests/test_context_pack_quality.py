"""Context pack quality: confidence, seed bias, graph rerank, procedures, caps."""

from __future__ import annotations

from brainkm.db.connection import connect
from brainkm.models.brain_config import BrainConfig
from brainkm.services.budget import BudgetLine
from brainkm.services.context_pack import (
    _apply_memory_subtype_caps,
    _pack_retrieval_confidence,
    _select_procedures_for_pack,
    compile_context_pack,
    resolve_pack_code_ref,
)
from tests.conftest import insert_edge, insert_node


def _mark_graph_imported(conn) -> None:
    conn.execute(
        """
        INSERT INTO graph_import_runs (id, started_at, completed_at, status, node_count, edge_count)
        VALUES ('run1', '2026-01-01T00:00:00Z', '2026-01-01T00:00:01Z', 'completed', 2, 1)
        """
    )


def test_pack_abstains_on_nonsense_query(brain_db) -> None:
    conn = connect(brain_db)
    try:
        _mark_graph_imported(conn)
        insert_node(
            conn,
            node_id="webllm",
            kind="code",
            subtype="function",
            title="test_prefetch_unknown_model()",
            path="tests/test_webllm_prefetch.py",
            content="unknown model prefetch",
        )
        insert_node(
            conn,
            node_id="proc",
            kind="procedure",
            subtype="tool_chain",
            title="Write → Shell",
            content="Tools: Write → Shell\n\n1. Write\n2. Shell",
        )
        for i in range(20):
            insert_node(
                conn,
                node_id=f"fill{i}",
                subtype="fact",
                title=f"filler fact {i}",
                content=f"unrelated content pad {i}",
            )
        conn.commit()
        pack = compile_context_pack(
            conn,
            "zzzznonexistent_symbol_xyz_12345 completely unknown module",
            config=BrainConfig(recall={"abstain_on_low_confidence": True}),
        )
        assert pack.confidence == "low"
        assert "Write → Shell" not in pack.pack_text
        assert "test_prefetch_unknown_model" not in pack.pack_text
        assert pack.graph_hint and "Low-confidence" in pack.graph_hint
    finally:
        conn.close()


def test_procedure_intent_keeps_tool_chain_and_boosts_slot(brain_db) -> None:
    from brainkm.services.context_pack import _select_procedures_for_pack

    conn = connect(brain_db)
    try:
        insert_node(
            conn,
            node_id="p1",
            kind="procedure",
            subtype="tool_chain",
            title="Write → Shell",
            content="Tools: Write → Shell\n\n1. Write\n2. Shell",
        )
        insert_node(
            conn,
            node_id="p2",
            kind="procedure",
            subtype="tool_chain",
            title="Write → Shell",
            content="Tools: Write → Shell\n\n1. Write\n2. Shell\n\nRelated context:\n- Redaction",
        )
        conn.commit()
        # Off-topic: zero overlap → empty
        off = _select_procedures_for_pack(
            conn, "antigravity distill shadow brain", seed_refs=None, seed_ids=[]
        )
        assert off == []
        # Procedure-shaped: keep one Write→Shell (title dedup)
        on = _select_procedures_for_pack(
            conn,
            "What tool chain do we usually use after Write?",
            seed_refs=None,
            seed_ids=[],
        )
        assert len(on) == 1
        assert on[0].title == "Write → Shell"
    finally:
        conn.close()

    graph = [
        BudgetLine("g1", "code", "file", "a.py", "", 10, 7, score=1.0),
        BudgetLine("g2", "code", "function", "f", "", 10, 9, score=0.9),
        BudgetLine("g3", "code", "function", "g", "", 10, 9, score=0.8),
        BudgetLine("g4", "code", "function", "h", "", 10, 9, score=0.7),
    ]
    assert (
        _pack_retrieval_confidence(
            memory_kept=[],
            graph_kept=graph,
            fts_bm25_by_id={},
            min_bm25_strength=3.0,
            explicit_seed_refs=True,
            abstained=False,
        )
        == "medium"
    )
    assert (
        _pack_retrieval_confidence(
            memory_kept=[],
            graph_kept=graph,
            fts_bm25_by_id={},
            min_bm25_strength=3.0,
            explicit_seed_refs=False,
            strong_query_seed=False,
            abstained=False,
        )
        == "low"
    )


def test_pack_confidence_uses_post_cap_top_by_score() -> None:
    # Higher score memory without BM25 → low; must not inherit other ids' BM25.
    memories = [
        BudgetLine("weak", "memory", "decision", "t", "c", 10, 0, score=9.0),
        BudgetLine("strong", "memory", "decision", "t2", "c2", 10, 0, score=1.0),
    ]
    label = _pack_retrieval_confidence(
        memory_kept=memories,
        graph_kept=[],
        fts_bm25_by_id={"strong": -15.0},
        min_bm25_strength=3.0,
        explicit_seed_refs=False,
        abstained=False,
    )
    assert label == "low"
    label_ok = _pack_retrieval_confidence(
        memory_kept=memories,
        graph_kept=[],
        fts_bm25_by_id={"weak": -15.0},
        min_bm25_strength=3.0,
        explicit_seed_refs=False,
        abstained=False,
    )
    assert label_ok == "high"


def test_resolve_pack_code_ref_prefers_file(brain_db) -> None:
    conn = connect(brain_db)
    try:
        insert_node(
            conn,
            node_id="fn",
            kind="code",
            subtype="function",
            title="set_items",
            path="brainkm/tui/widgets/status_panel.py",
            content="def set_items",
        )
        insert_node(
            conn,
            node_id="file",
            kind="code",
            subtype="file",
            title="status_panel.py",
            path="brainkm/tui/widgets/status_panel.py",
            content="module",
        )
        conn.commit()
        assert (
            resolve_pack_code_ref(conn, "brainkm/tui/widgets/status_panel.py") == "file"
        )
        assert resolve_pack_code_ref(conn, "no/such/path.py") is None
    finally:
        conn.close()


def test_resolve_pack_code_ref_ignores_commit_fts_hit(brain_db) -> None:
    """Docs-path fragments like codex.md must not seed graph from commit nodes."""
    conn = connect(brain_db)
    try:
        insert_node(
            conn,
            node_id="commit-codex",
            kind="commit",
            subtype="git",
            title="fix: update codex.md install guide",
            content="files: budget.py context_pack.py docs/install/codex.md",
        )
        insert_node(
            conn,
            node_id="install-file",
            kind="code",
            subtype="file",
            title="install.py",
            path="brainkm/brainkm/services/install.py",
            content="build_codex_hooks_config",
        )
        conn.commit()
        assert resolve_pack_code_ref(conn, "codex.md") is None
        assert resolve_pack_code_ref(conn, "commit-codex") is None
    finally:
        conn.close()


def test_pre_tool_docs_path_seeds_related_code_not_commit_files(brain_db) -> None:
    """PreTool Edit on docs/install/codex.md should neighborhood install/codex code."""
    from brainkm.services.context_pack import compile_pre_tool_pack

    conn = connect(brain_db)
    try:
        _mark_graph_imported(conn)
        insert_node(
            conn,
            node_id="commit-poison",
            kind="commit",
            subtype="git",
            title="fix: context_pack quality and update codex install guide",
            content="files: budget.py context_pack.py docs/install/codex.md",
        )
        insert_node(
            conn,
            node_id="budget-file",
            kind="code",
            subtype="file",
            title="budget.py",
            path="brainkm/brainkm/services/budget.py",
            content="token budgets",
        )
        insert_node(
            conn,
            node_id="install-file",
            kind="code",
            subtype="file",
            title="install.py",
            path="brainkm/brainkm/services/install.py",
            content="build_codex_hooks_config write_codex_hooks",
        )
        insert_node(
            conn,
            node_id="codex-hooks-fn",
            kind="code",
            subtype="function",
            title="build_codex_hooks_config()",
            path="brainkm/brainkm/services/install.py",
            content="def build_codex_hooks_config",
        )
        insert_edge(
            conn,
            edge_id="e-install-fn",
            from_id="install-file",
            to_id="codex-hooks-fn",
            relationship="contains",
        )
        conn.commit()

        pack = compile_pre_tool_pack(
            conn,
            {"tool_name": "Edit", "tool_input": {"path": "docs/install/codex.md"}},
            config=BrainConfig(
                budget={
                    "total_tokens": 1500,
                    "pre_tool": {"graph_neighborhood": 400, "procedure_expanded": 250},
                },
                recall={"abstain_on_low_confidence": False},
            ),
        )
        assert pack is not None
        text = pack.pack_text.lower()
        assert "install.py" in text or "build_codex_hooks" in text
        # Must not be dominated by the commit's unrelated touched files alone.
        assert "commit-poison" not in pack.truncation.included_ids
    finally:
        conn.close()


def test_seed_refs_boost_about_file_memory(brain_db) -> None:
    conn = connect(brain_db)
    try:
        _mark_graph_imported(conn)
        insert_node(
            conn,
            node_id="panel",
            kind="code",
            subtype="file",
            title="status_panel.py",
            path="brainkm/tui/widgets/status_panel.py",
        )
        insert_node(
            conn,
            node_id="local-dec",
            subtype="decision",
            title="StatusPanel muted info colors",
            content=(
                "Use info for RAM/GPU system metrics and muted for secondary rows "
                "in brainkm/tui/widgets/status_panel.py"
            ),
        )
        insert_node(
            conn,
            node_id="hook-noise",
            subtype="decision",
            title="stdin hook always prints JSON",
            content="preToolUse sessionStart must print JSON on stdout for Cursor hooks.",
        )
        insert_edge(
            conn,
            edge_id="af1",
            from_id="local-dec",
            to_id="panel",
            relationship="about_file",
        )
        # Filler so BM25/IDF is meaningful
        for i in range(25):
            insert_node(
                conn,
                node_id=f"fill{i}",
                subtype="fact",
                title=f"unrelated filler {i}",
                content=f"hooks wal checkpoint graph sync note {i}",
            )
        conn.commit()
        pack = compile_context_pack(
            conn,
            "dashboard Status panel model row muted system info metrics",
            config=BrainConfig(recall={"abstain_on_low_confidence": False}),
            seed_refs=["brainkm/tui/widgets/status_panel.py", "missing/nope.py"],
            include_structured=True,
        )
        titles = [n.title for n in pack.neurons]
        assert any("StatusPanel" in t or "muted" in t.lower() for t in titles)
        # Seed-local should appear; hook noise should not dominate alone.
        if pack.neurons:
            assert pack.neurons[0].node_id == "local-dec" or "StatusPanel" in pack.pack_text
    finally:
        conn.close()


def test_graph_rerank_prefers_set_items_over_action(brain_db) -> None:
    conn = connect(brain_db)
    try:
        _mark_graph_imported(conn)
        insert_node(
            conn,
            node_id="dash",
            kind="code",
            subtype="file",
            title="dashboard.py",
            path="brainkm/tui/screens/dashboard.py",
        )
        insert_node(
            conn,
            node_id="panel",
            kind="code",
            subtype="file",
            title="status_panel.py",
            path="brainkm/tui/widgets/status_panel.py",
        )
        insert_node(
            conn,
            node_id="set_items",
            kind="code",
            subtype="function",
            title="set_items",
            path="brainkm/tui/widgets/status_panel.py",
            content="def set_items",
        )
        insert_node(
            conn,
            node_id="load_ollama",
            kind="code",
            subtype="function",
            title="_load_ollama_status",
            path="brainkm/tui/screens/dashboard.py",
            content="def _load_ollama_status",
        )
        insert_node(
            conn,
            node_id="action_refresh",
            kind="code",
            subtype="function",
            title="action_refresh",
            path="brainkm/tui/screens/dashboard.py",
            content="def action_refresh",
        )
        for edge_id, frm, to in [
            ("e1", "dash", "load_ollama"),
            ("e2", "dash", "action_refresh"),
            ("e3", "panel", "set_items"),
            ("e4", "dash", "panel"),
        ]:
            insert_edge(
                conn,
                edge_id=edge_id,
                from_id=frm,
                to_id=to,
                relationship="contains" if "action" not in to and to != "panel" else "imports",
            )
        # contains for methods
        insert_edge(
            conn,
            edge_id="e5",
            from_id="dash",
            to_id="load_ollama",
            relationship="method",
        )
        insert_edge(
            conn,
            edge_id="e6",
            from_id="dash",
            to_id="action_refresh",
            relationship="method",
        )
        insert_edge(
            conn,
            edge_id="e7",
            from_id="panel",
            to_id="set_items",
            relationship="method",
        )
        conn.commit()
        pack = compile_context_pack(
            conn,
            "dashboard Status panel model row Ollama doctor muted system info metrics",
            config=BrainConfig(recall={"abstain_on_low_confidence": False}),
            seed_refs=[
                "brainkm/tui/screens/dashboard.py",
                "brainkm/tui/widgets/status_panel.py",
            ],
            include_structured=True,
        )
        titles = [n.title for n in pack.graph_nodes]
        assert "set_items" in titles or "_load_ollama_status" in titles
        # action_refresh may appear but should not be the sole useful hit
        if "action_refresh" in titles and "set_items" in titles:
            assert titles.index("set_items") < titles.index("action_refresh")
    finally:
        conn.close()


def test_action_demotion_counter_fixture_keeps_action_approve(brain_db) -> None:
    """When action_* is the answer, demotion must not hard-kill it."""
    conn = connect(brain_db)
    try:
        _mark_graph_imported(conn)
        insert_node(
            conn,
            node_id="dash",
            kind="code",
            subtype="file",
            title="dashboard.py",
            path="brainkm/tui/screens/dashboard.py",
        )
        insert_node(
            conn,
            node_id="approve",
            kind="code",
            subtype="function",
            title="action_approve_selected",
            path="brainkm/tui/screens/dashboard.py",
            content="def action_approve_selected",
        )
        insert_node(
            conn,
            node_id="other",
            kind="code",
            subtype="function",
            title="set_loading",
            path="brainkm/tui/screens/dashboard.py",
            content="def set_loading",
        )
        insert_edge(
            conn,
            edge_id="e1",
            from_id="dash",
            to_id="approve",
            relationship="method",
        )
        insert_edge(
            conn,
            edge_id="e2",
            from_id="dash",
            to_id="other",
            relationship="method",
        )
        conn.commit()
        pack = compile_context_pack(
            conn,
            "how does action_approve_selected approve review rows on the dashboard",
            config=BrainConfig(recall={"abstain_on_low_confidence": False}),
            seed_refs=["brainkm/tui/screens/dashboard.py"],
            include_structured=True,
        )
        titles = [n.title for n in pack.graph_nodes]
        assert "action_approve_selected" in titles
    finally:
        conn.close()


def test_procedure_dedup_and_workflow_fill(brain_db) -> None:
    conn = connect(brain_db)
    try:
        for i in range(5):
            insert_node(
                conn,
                node_id=f"tc{i}",
                kind="procedure",
                subtype="tool_chain",
                title="Write → Shell",
                content=f"Tools: Write → Shell\n\n1. Write\n2. Shell\nvariant {i}",
            )
        insert_node(
            conn,
            node_id="wf1",
            kind="procedure",
            subtype="workflow",
            title="Status panel refresh workflow",
            content="Refresh ollama doctor then set_items on StatusPanel",
        )
        conn.commit()
        lines = _select_procedures_for_pack(
            conn,
            "Status panel Ollama doctor set_items",
            seed_refs=["status_panel.py"],
            seed_ids=[],
        )
        titles = [line.title for line in lines]
        assert titles.count("Write → Shell") <= 1
        assert any(line.subtype == "workflow" for line in lines) or "Status panel" in " ".join(
            titles
        )
    finally:
        conn.close()


def test_subtype_caps_top_n_by_score() -> None:
    lines = [
        BudgetLine("e_low", "memory", "error", "old err", "x", 5, 3, score=1.0),
        BudgetLine("e_high", "memory", "error", "hot err", "y", 5, 3, score=9.0),
        BudgetLine("d1", "memory", "decision", "dec", "z", 5, 0, score=5.0),
        BudgetLine("obs1", "memory", "observation", "obs", "o", 5, 11, score=8.0),
        BudgetLine("obs2", "memory", "observation", "obs2", "o2", 5, 11, score=7.0),
        BudgetLine("pat", "memory", "pattern", "pat", "p", 5, 4, score=2.0),
    ]
    kept = _apply_memory_subtype_caps(lines, debug=False)
    ids = {line.node_id for line in kept}
    assert "e_high" in ids
    assert "e_low" not in ids
    assert "obs1" in ids
    assert "obs2" not in ids
    assert "pat" in ids  # uncapped other subtype
    assert "d1" in ids

    kept_dbg = _apply_memory_subtype_caps(lines, debug=True)
    err_ids = [line.node_id for line in kept_dbg if line.subtype == "error"]
    assert len(err_ids) == 2
