"""Tests for nodal lifecycle: promote lineage, about_file, diversify, concepts."""

from __future__ import annotations

from pathlib import Path

from brainkm.db.connection import connect
from brainkm.db.migrate import migrate
from brainkm.models.brain_config import BrainConfig, CaptureConfig
from brainkm.services.diversify import diversify_ranked
from brainkm.services.file_history import file_history
from brainkm.services.lifecycle import EPISODE_SUBTYPE, stage_of
from brainkm.services.memory import create_neuron, remember_neuron
from brainkm.services.neuron_index import index_neuron_links
from brainkm.services.observe import OBSERVATION_SUBTYPE, promote_session_observations
from brainkm.services.provenance import load_provenance
from brainkm.services.search import RankedNode, recall_with_bfs


def _tmp_brain(tmp_path: Path):
    db = tmp_path / ".brain" / "brain.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    migrate(db_path=db, run_integrity_check=False)
    return connect(db)


def test_stage_of() -> None:
    assert stage_of(kind="memory", subtype="observation") == "observation"
    assert stage_of(kind="memory", subtype=EPISODE_SUBTYPE) == "episode"
    assert stage_of(kind="memory", subtype="decision") == "semantic"
    assert stage_of(kind="procedure", subtype="tool_chain") == "procedure"


def test_promote_creates_distilled_from_and_path(tmp_path: Path) -> None:
    conn = _tmp_brain(tmp_path)
    try:
        code = create_neuron(
            conn,
            title="auth.py",
            content="src/auth.py",
            kind="code",
            subtype="file",
            path="src/auth.py",
            source="test",
        )
        obs = remember_neuron(
            conn,
            title="tool: Write → src/auth.py",
            content="Rewrote token refresh to retry once on a 401 before failing.",
            subtype=OBSERVATION_SUBTYPE,
            path="src/auth.py",
            session_id="sess-1",
            source="auto_observe",
            tags=["observe_fp:abc", "tool:Write"],
            confidence=0.3,
        )
        cfg = BrainConfig(capture=CaptureConfig(auto_observe=True))
        result = promote_session_observations(
            conn, session_id="sess-1", config=cfg, project_dir=tmp_path
        )
        assert result.promoted == 1
        row = conn.execute(
            """
            SELECT id, path FROM nodes
            WHERE source = 'observe_promote' AND valid_until IS NULL
            """
        ).fetchone()
        assert row is not None
        assert row[1] == "src/auth.py"
        chain = load_provenance(conn, row[0])
        assert any(link.via == "distilled_from" and link.id == obs.id for link in chain.links)
        # about_file edge to code
        edge = conn.execute(
            """
            SELECT 1 FROM edges
            WHERE from_id = ? AND to_id = ? AND relationship = 'about_file'
            """,
            (row[0], code.id),
        ).fetchone()
        assert edge is not None
        # A promoted successful tool call is an observation, never a decision —
        # decision is uncapped in packs and must stay reserved for real ones.
        subtype = conn.execute("SELECT subtype FROM nodes WHERE id = ?", (row[0],)).fetchone()[0]
        assert subtype == OBSERVATION_SUBTYPE
    finally:
        conn.close()


def test_promote_archives_trivial_observation_bodies(tmp_path: Path) -> None:
    """An observation whose whole body is "ok" carries nothing — archive it."""
    conn = _tmp_brain(tmp_path)
    try:
        remember_neuron(
            conn,
            title="tool: Bash → wc -l",
            content="ok",
            subtype=OBSERVATION_SUBTYPE,
            session_id="sess-1",
            source="auto_observe",
            tags=["observe_fp:def", "tool:Bash"],
            confidence=0.3,
        )
        cfg = BrainConfig(capture=CaptureConfig(auto_observe=True))
        result = promote_session_observations(
            conn, session_id="sess-1", config=cfg, project_dir=tmp_path
        )
        assert result.promoted == 0
        assert result.archived == 1
    finally:
        conn.close()


def test_about_file_and_file_history(tmp_path: Path) -> None:
    conn = _tmp_brain(tmp_path)
    try:
        code = create_neuron(
            conn,
            title="memory.py",
            content="brainkm/services/memory.py",
            kind="code",
            subtype="file",
            path="brainkm/services/memory.py",
            source="test",
        )
        mem = remember_neuron(
            conn,
            title="Token budget on packs",
            content="Enforce 1500 tokens in brainkm/services/memory.py always.",
            subtype="decision",
            tags=["tokens", "budget"],
            source="test",
        )
        linked = index_neuron_links(
            conn,
            mem.id,
            title=mem.title,
            content=mem.content or "",
            tags=["tokens", "budget"],
            kind="memory",
        )
        assert code.id in linked
        code_id, items = file_history(conn, "brainkm/services/memory.py")
        assert code_id == code.id
        assert any(i.node_id == mem.id for i in items)
        # concept materialization
        concept = conn.execute(
            "SELECT id FROM nodes WHERE kind = 'concept' AND valid_until IS NULL LIMIT 1"
        ).fetchone()
        assert concept is not None
    finally:
        conn.close()


def test_diversify_max_per_session() -> None:
    items = [
        RankedNode(
            node_id=f"n{i}",
            activation=1.0,
            score=10 - i,
            kind="memory",
            subtype="decision",
            title=f"t{i}",
            session_id="s1" if i < 5 else "s2",
        )
        for i in range(8)
    ]
    kept = diversify_ranked(items, max_per_session=3, max_per_kind={"memory": 10})
    assert sum(1 for n in kept if n.session_id == "s1") <= 3
    assert sum(1 for n in kept if n.session_id == "s2") <= 3


def test_recall_path_seed(tmp_path: Path) -> None:
    conn = _tmp_brain(tmp_path)
    try:
        code = create_neuron(
            conn,
            title="hooks.py",
            content="brainkm/services/hooks.py",
            kind="code",
            subtype="file",
            path="brainkm/services/hooks.py",
            source="test",
        )
        mem = remember_neuron(
            conn,
            title="PreCompact handover",
            content="Always run handover before compact; see brainkm/services/hooks.py",
            subtype="rule",
            tags=["compaction"],
            source="test",
        )
        index_neuron_links(
            conn,
            mem.id,
            title=mem.title,
            content=mem.content or "",
            tags=["compaction"],
        )
        conn.commit()
        result = recall_with_bfs(
            conn,
            "what about brainkm/services/hooks.py compaction",
            recall=BrainConfig().recall,
        )
        ids = {n.node_id for n in result.nodes}
        assert mem.id in ids or code.id in ids or not result.abstained
    finally:
        conn.close()
