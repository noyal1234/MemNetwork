"""Recall pack quality: confidence, session chunks, concepts, path landing."""

from __future__ import annotations

from pathlib import Path

from brainkm.db.connection import connect
from brainkm.db.migrate import migrate
from brainkm.models.brain_config import BrainConfig, RecallConfig
from brainkm.models.distill import DistilledNeuron
from brainkm.models.schemas import RecallRequest
from brainkm.services.confidence import confidence_for_top_result, score_confidence
from brainkm.services.diversify import diversify_ranked
from brainkm.services.mcp_results import ranked_to_neuron, resolve_display_path
from brainkm.services.memory import create_neuron, remember_neuron
from brainkm.services.quality import passes_quality_gate, passes_stored_neuron_gate
from brainkm.services.recall_dedup import (
    SessionChunkHit,
    collapse_near_duplicate_chunks,
    deduped_session_chunks,
)
from brainkm.services.remember_links import extract_path_mentions
from brainkm.services.search import RankedNode, recall_with_bfs
from brainkm.tools.dispatch import handle_recall
from tests.conftest import insert_edge, insert_node


def _tmp_brain(tmp_path: Path):
    db = tmp_path / ".brain" / "brain.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    migrate(db_path=db, run_integrity_check=False)
    return connect(db)


def test_score_confidence_bm25_thresholds() -> None:
    assert score_confidence(top_score=-3.0, result_count=1) == "medium"
    assert score_confidence(top_score=-12.0, result_count=1) == "high"
    assert score_confidence(top_score=-0.5, result_count=1) == "low"
    # Tiny PPR-like scores must not look like strong BM25.
    assert score_confidence(top_score=0.08, result_count=1) == "low"


def test_confidence_for_top_result_uses_direct_bm25_not_pool() -> None:
    # Top node is graph-only; strong BM25 elsewhere must not inflate confidence.
    label = confidence_for_top_result(
        abstained=False,
        result_count=3,
        top_node_id="graph-only",
        fts_bm25_by_id={"seed-a": -15.0},
        min_bm25_strength=3.0,
    )
    assert label == "low"

    label_ok = confidence_for_top_result(
        abstained=False,
        result_count=1,
        top_node_id="seed-a",
        fts_bm25_by_id={"seed-a": -4.0},
        min_bm25_strength=3.0,
    )
    assert label_ok == "medium"


def test_handle_recall_confidence_from_fts_not_ppr(tmp_path: Path) -> None:
    conn = _tmp_brain(tmp_path)
    try:
        # Filler corpus so FTS5 BM25 IDF magnitudes are in the production range
        # (single-doc DBs yield near-zero |bm25| and falsely look "low").
        for i in range(40):
            insert_node(
                conn,
                node_id=f"fill{i}",
                subtype="fact",
                title=f"hooks graph sync note {i}",
                content=f"unrelated filler about session start and wal checkpoint {i}",
            )
        insert_node(
            conn,
            node_id="dec1",
            subtype="decision",
            title="Apache-2.0 Phase A done; PyPI rename deferred",
            content=(
                "Public package release PyPI publish deferred until installable name finalized. "
                "Checklist: docs/PUBLIC_RELEASE_CHECKLIST.md"
            ),
        )
        conn.commit()
        result = handle_recall(
            conn,
            RecallRequest(query="public package release PyPI publish", limit=5),
            config=BrainConfig(recall={"abstain_on_low_confidence": False}),
            project_dir=tmp_path,
        )
        assert result.abstained is False
        assert result.nodes
        assert result.nodes[0].kind == "memory"
        # Direct FTS hit on the decision should not stay stuck at low solely due to PPR scale.
        assert result.confidence in {"medium", "high"}
        assert result.sources == {}
        assert result.nodes[0].path == "docs/PUBLIC_RELEASE_CHECKLIST.md"
    finally:
        conn.close()


def test_session_chunks_magnitude_gate_and_shingle_dedup(brain_db) -> None:
    conn = connect(brain_db)
    try:
        insert_node(conn, node_id="n1", title="JWT policy", content="token expiry rules")
        # Sliding-window overlap (shared mid body).
        base = (
            "The JWT policy discussion covers token expiry rules and rotation. "
            "Agents must refresh before the deadline. "
        )
        conn.execute(
            """
            INSERT INTO session_chunks (id, session_id, role, content, ts)
            VALUES
              ('c1', 's1', 'user', ?, datetime('now')),
              ('c2', 's1', 'user', ?, datetime('now')),
              ('c3', 's1', 'user', ?, datetime('now'))
            """,
            (
                "prefixAAA " + base + " suffixOne",
                "prefixBBB " + base + " suffixTwo",
                "completely unrelated transcript about graph sync auto refresh",
            ),
        )
        conn.commit()
        strong = SessionChunkHit("a", "x" * 40, score=-8.0)
        weak = SessionChunkHit("b", "y" * 40, score=-0.5)
        assert abs(weak.score) < 3.0
        collapsed = collapse_near_duplicate_chunks(
            [
                SessionChunkHit("c1", "prefixAAA " + base + " suffixOne", -9.0),
                SessionChunkHit("c2", "prefixBBB " + base + " suffixTwo", -8.5),
            ]
        )
        assert len(collapsed) == 1

        hits = deduped_session_chunks(
            conn,
            "JWT policy token expiry",
            {"n1"},
            min_bm25_strength=3.0,
        )
        ids = [h.chunk_id for h in hits]
        assert len(ids) == len(set(ids))
        for hit in hits:
            assert abs(hit.score) >= 3.0
        assert abs(strong.score) >= 3.0
    finally:
        conn.close()


def test_deduped_session_chunks_empty_neurons(brain_db) -> None:
    conn = connect(brain_db)
    try:
        assert deduped_session_chunks(conn, "q", set()) == []
    finally:
        conn.close()


def test_diversify_concept_cap_zero_backfills_to_limit() -> None:
    items = [
        RankedNode(
            node_id=f"n{i}",
            activation=1.0,
            score=10 - i,
            kind="concept" if i in {1, 3} else "memory",
            subtype="tag" if i in {1, 3} else "decision",
            title=f"t{i}",
            session_id=f"s{i}",
        )
        for i in range(5)
    ]
    # Positions 1 and 3 are concepts; with cap 0, backfill from later memories.
    extras = [
        RankedNode(
            node_id=f"m{i}",
            activation=0.5,
            score=1.0 - i * 0.01,
            kind="memory",
            subtype="fact",
            title=f"extra{i}",
            session_id=f"sx{i}",
        )
        for i in range(3)
    ]
    kept = diversify_ranked(
        items + extras,
        max_per_session=10,
        max_per_kind={"memory": 8, "concept": 0},
    )
    assert all(n.kind != "concept" for n in kept)
    assert len(kept) >= 5
    assert len(kept[:5]) == 5


def test_recall_excludes_concepts_from_pack(tmp_path: Path) -> None:
    conn = _tmp_brain(tmp_path)
    try:
        for i in range(5):
            remember_neuron(
                conn,
                title=f"PyPI publish decision {i}",
                content=f"Public release checklist step {i} for PyPI package publish.",
                subtype="decision",
                confidence=0.9,
                source="test",
            )
        create_neuron(
            conn,
            title="Concept: pypi",
            content="Concept: pypi",
            kind="concept",
            subtype="tag",
            source="test",
        )
        create_neuron(
            conn,
            title="Concept: public-release-checklist",
            content="Concept: public-release-checklist",
            kind="concept",
            subtype="tag",
            source="test",
        )
        conn.commit()
        result = recall_with_bfs(
            conn,
            "PyPI publish public release",
            recall=RecallConfig(abstain_on_low_confidence=False),
        )
        assert result.abstained is False
        kinds = {n.kind for n in result.nodes[:5]}
        assert "concept" not in kinds
        assert len(result.nodes[:5]) == 5
    finally:
        conn.close()


def test_extract_path_mentions_false_positives() -> None:
    assert extract_path_mentions("Use os.path to join segments") == []
    assert extract_path_mentions("See https://pypi.org/project/brainkm/") == []
    assert extract_path_mentions("open foo.exe carefully") == []
    assert extract_path_mentions(
        "Follow docs/PUBLIC_RELEASE_CHECKLIST.md before tagging"
    ) == ["docs/PUBLIC_RELEASE_CHECKLIST.md"]


def test_resolve_display_path_earliest_mention_and_about_file(tmp_path: Path) -> None:
    conn = _tmp_brain(tmp_path)
    try:
        code_a = create_neuron(
            conn,
            title="a.py",
            content="a",
            kind="code",
            subtype="file",
            path="brainkm/a.py",
            source="test",
        )
        code_b = create_neuron(
            conn,
            title="b.py",
            content="b",
            kind="code",
            subtype="file",
            path="brainkm/b.py",
            source="test",
        )
        mem = remember_neuron(
            conn,
            title="Multi file decision",
            content="Touch brainkm/b.py then brainkm/a.py for the rename.",
            subtype="decision",
            source="test",
        )
        insert_edge(
            conn,
            edge_id="e1",
            from_id=mem.id,
            to_id=code_a.id,
            relationship="about_file",
        )
        insert_edge(
            conn,
            edge_id="e2",
            from_id=mem.id,
            to_id=code_b.id,
            relationship="about_file",
        )
        conn.commit()
        # Earliest content mention wins over edge order.
        path = resolve_display_path(
            conn,
            node_id=mem.id,
            title=mem.title,
            content=mem.content,
            existing_path=None,
        )
        assert path == "brainkm/b.py"

        # No mentions → stable about_file rowid order.
        mem2 = remember_neuron(
            conn,
            title="Linked without path text",
            content="Rename the installable package carefully.",
            subtype="decision",
            source="test",
        )
        insert_edge(
            conn,
            edge_id="e3",
            from_id=mem2.id,
            to_id=code_b.id,
            relationship="about_file",
        )
        insert_edge(
            conn,
            edge_id="e4",
            from_id=mem2.id,
            to_id=code_a.id,
            relationship="about_file",
        )
        conn.commit()
        path2 = resolve_display_path(
            conn,
            node_id=mem2.id,
            title=mem2.title,
            content=mem2.content,
            existing_path=None,
        )
        assert path2 == "brainkm/b.py"

        ranked = RankedNode(
            node_id=mem.id,
            activation=0.1,
            score=0.05,
            kind="memory",
            subtype="decision",
            title=mem.title,
            content=mem.content,
        )
        neuron = ranked_to_neuron(conn, ranked)
        assert neuron is not None
        assert neuron.path == "brainkm/b.py"
    finally:
        conn.close()


def test_quality_gate_rejects_user_questions() -> None:
    item = DistilledNeuron(
        subtype="fact",
        title="Can you go through the modified and untracked",
        body="Can you go through the modified and untracked files whether they are supposed to be pushed?",
    )
    assert passes_quality_gate(item) is False
    assert (
        passes_stored_neuron_gate(
            title=item.title,
            content=item.body,
        )
        is False
    )
