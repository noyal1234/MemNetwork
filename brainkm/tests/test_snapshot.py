"""Tests for frozen injection snapshots and live recall."""

import json

from brainkm.db.connection import connect
from brainkm.models.brain_config import BrainConfig, RecallConfig
from brainkm.models.snapshot import SnapshotNeuron
from brainkm.services.memory import create_neuron, remember_neuron, token_count
from brainkm.services.recall import recall_live
from brainkm.services.snapshot import (
    build_frozen_snapshot,
    clamp_injection_pack,
    get_frozen_snapshot,
    render_injection_pack,
    select_injection_neurons,
)


def test_render_injection_pack_groups_sections() -> None:
    pack = render_injection_pack(
        [
            SnapshotNeuron("1", "memory", "rule", "Never log secrets", "Redact keys", 10),
            SnapshotNeuron("2", "memory", "context", "Working on auth", None, 5),
        ]
    )
    assert "Rules & decisions" in pack
    assert "Context" in pack
    assert "Never log secrets" in pack


def test_render_injection_pack_includes_graph_status() -> None:
    pack = render_injection_pack(
        [SnapshotNeuron("1", "memory", "rule", "Rule", "Body", 5)],
        graph_status=(
            "Code graph: 12 nodes / 34 edges. "
            "For call/import/blast-radius use traverse; for multi-file task context "
            "use context_pack with a symbol — then verify in source before editing."
        ),
    )
    assert "Code graph: 12 nodes / 34 edges" in pack
    assert "traverse" in pack


def test_frozen_snapshot_advertises_graph_when_imported(brain_db) -> None:
    from tests.conftest import insert_node

    conn = connect(brain_db)
    try:
        conn.execute(
            """
            INSERT INTO graph_import_runs (id, started_at, completed_at, status, node_count, edge_count)
            VALUES ('run1', '2026-01-01T00:00:00Z', '2026-01-01T00:00:01Z', 'completed', 1, 0)
            """
        )
        insert_node(
            conn,
            node_id="code1",
            kind="code",
            subtype="file",
            title="a.py",
            path="a.py",
        )
        create_neuron(
            conn,
            title="Use JWT for API authentication",
            content="Access tokens expire after 15 minutes.",
            subtype="decision",
            node_id="decision-jwt",
        )
        conn.commit()

        snapshot = build_frozen_snapshot(conn, "sess-graph", BrainConfig())
        assert "Code graph:" in snapshot.pack_text
        assert "traverse" in snapshot.pack_text
    finally:
        conn.close()


def test_frozen_snapshot_excludes_mid_session_remember(brain_db) -> None:
    conn = connect(brain_db)
    try:
        create_neuron(
            conn,
            title="Use JWT for API authentication",
            content="Access tokens expire after 15 minutes.",
            subtype="decision",
            node_id="decision-jwt",
        )
        conn.commit()

        snapshot = build_frozen_snapshot(conn, "sess-live", BrainConfig())
        assert "decision-jwt" in snapshot.neuron_ids

        remember_neuron(
            conn,
            title="Cache session state in Redis",
            content="Use Redis for ephemeral session storage during rollout.",
            subtype="decision",
        )
        conn.commit()

        frozen = get_frozen_snapshot(conn, "sess-live")
        assert frozen is not None
        assert "decision-jwt" in frozen.neuron_ids
        assert len(frozen.neuron_ids) == len(snapshot.neuron_ids)
        assert "Redis" not in frozen.pack_text

        snapshot_again = build_frozen_snapshot(conn, "sess-live", BrainConfig())
        assert snapshot_again.neuron_ids == snapshot.neuron_ids

        live = recall_live(
            conn,
            "Redis session storage",
            recall=RecallConfig(abstain_on_low_confidence=False),
        )
        assert live.source == "live_db"
        assert any("Redis" in node.title for node in live.nodes)
    finally:
        conn.close()


def test_select_injection_neurons_respects_pinned_and_rules(brain_db) -> None:
    conn = connect(brain_db)
    try:
        create_neuron(
            conn,
            title="Pinned architectural anchor",
            content="SQLite is the source of truth.",
            subtype="fact",
            node_id="pinned-1",
        )
        conn.execute("UPDATE nodes SET user_pinned = 1 WHERE id = 'pinned-1'")
        create_neuron(
            conn,
            title="Always run migrations before hooks",
            content="brainkm migrate on SessionStart.",
            subtype="rule",
            node_id="rule-1",
        )
        conn.commit()

        selected = select_injection_neurons(conn, BrainConfig())
        ids = {n.node_id for n in selected}
        assert "pinned-1" in ids
        assert "rule-1" in ids
    finally:
        conn.close()


def test_frozen_snapshot_respects_total_token_cap(brain_db) -> None:
    conn = connect(brain_db)
    try:
        for i in range(40):
            create_neuron(
                conn,
                title=f"Pinned architectural decision {i}",
                content=(
                    "Prefer SQLite FTS5 for project memory and keep injection packs "
                    "bounded under the configured token budget. Verify in source. "
                )
                * 6,
                subtype="decision",
                node_id=f"dec-{i}",
            )
            conn.execute(
                "UPDATE nodes SET user_pinned = 1 WHERE id = ?",
                (f"dec-{i}",),
            )
        conn.commit()

        config = BrainConfig(budget={"total_tokens": 400})
        snapshot = build_frozen_snapshot(conn, "sess-budget", config)
        assert snapshot.token_count <= 400
        assert token_count(snapshot.pack_text) <= 400
    finally:
        conn.close()


def test_clamp_injection_pack_drops_overflow() -> None:
    neurons = [
        SnapshotNeuron(
            f"n{i}",
            "memory",
            "decision",
            f"Decision {i}",
            "Body text about architecture choices that should be truncated. " * 20,
            80,
        )
        for i in range(20)
    ]
    kept, pack = clamp_injection_pack(neurons, graph_status=None, total_tokens=200)
    assert token_count(pack) <= 200
    assert len(kept) < len(neurons)


def test_session_start_hook_builds_snapshot(tmp_path) -> None:
    from brainkm.services.hooks import run_session_start

    db_path = tmp_path / ".brain" / "brain.db"
    result = run_session_start(
        json.dumps({"session_id": "hook-sess"}),
        project_dir=tmp_path,
        config=BrainConfig(),
    )
    assert result.skipped is False
    assert result.additional_context is not None
    assert "frozen snapshot" in result.additional_context

    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM session_snapshots WHERE session_id = ?",
            ("hook-sess",),
        ).fetchone()
        assert row is not None
    finally:
        conn.close()
