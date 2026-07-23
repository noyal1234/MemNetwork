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


def test_pack_confidence_never_density_graph_only() -> None:
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
