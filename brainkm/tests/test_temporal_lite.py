"""Tests for temporal-lite audit_log and trigger-maintained valid_until."""

import json

import pytest

from brainkm.db.connection import connect
from brainkm.services.audit import append_event, list_node_events
from brainkm.services.memory import (
    create_neuron,
    forget_neuron,
    is_active_at,
    list_active_nodes,
    supersede_neuron,
)


def test_create_neuron_sets_valid_from_and_created_event(brain_db) -> None:
    conn = connect(brain_db)
    try:
        record = create_neuron(
            conn,
            title="JWT expiry policy",
            content="Access tokens expire after 15 minutes",
            subtype="decision",
            session_id="sess-1",
            valid_from="2026-06-01T10:00:00+00:00",
        )
        conn.commit()

        assert record.valid_from == "2026-06-01T10:00:00+00:00"
        assert record.valid_until is None

        events = list_node_events(conn, record.id, event_type="created")
        assert len(events) == 1
        payload = json.loads(events[0]["payload"])
        assert payload["valid_from"] == "2026-06-01T10:00:00+00:00"
        assert payload["session_id"] == "sess-1"
    finally:
        conn.close()


def test_supersede_materializes_valid_until_from_audit_log_only(brain_db) -> None:
    conn = connect(brain_db)
    try:
        old = create_neuron(
            conn,
            node_id="old-jwt",
            title="JWT expiry 30 minutes",
            content="Old policy",
            subtype="decision",
            valid_from="2026-06-01T10:00:00+00:00",
        )
        conn.commit()

        new, retired = supersede_neuron(
            conn,
            old.id,
            title="JWT expiry 15 minutes",
            content="Updated policy",
            subtype="decision",
        )
        conn.commit()

        assert new.valid_until is None
        assert retired.valid_until is not None

        events = list_node_events(conn, old.id, event_type="superseded")
        assert len(events) == 1
        payload = json.loads(events[0]["payload"])
        assert payload["superseded_by"] == new.id
        assert payload["valid_until"] == retired.valid_until

        edge = conn.execute(
            """
            SELECT relationship FROM edges
            WHERE from_id = ? AND to_id = ?
            """,
            (new.id, old.id),
        ).fetchone()
        assert edge[0] == "supersedes"
    finally:
        conn.close()


def test_forget_materializes_valid_until_from_audit_log_only(brain_db) -> None:
    conn = connect(brain_db)
    try:
        neuron = create_neuron(conn, node_id="to-forget", title="Temporary note")
        conn.commit()

        archived = forget_neuron(conn, neuron.id, reason="user request")
        conn.commit()

        assert archived.valid_until is not None
        events = list_node_events(conn, neuron.id, event_type="forgotten")
        assert len(events) == 1
        payload = json.loads(events[0]["payload"])
        assert payload["reason"] == "user request"
        assert payload["valid_until"] == archived.valid_until
    finally:
        conn.close()


def test_direct_valid_until_update_is_not_used_by_memory_service(brain_db) -> None:
    """Memory service path never UPDATEs valid_until — only audit_log triggers do."""
    conn = connect(brain_db)
    try:
        neuron = create_neuron(conn, node_id="audit-only", title="Audit driven")
        conn.commit()

        append_event(
            conn,
            "superseded",
            node_id=neuron.id,
            payload={"valid_until": "2026-06-02T12:00:00+00:00", "superseded_by": "new-id"},
            ts="2026-06-02T12:00:00+00:00",
        )
        conn.commit()

        row = conn.execute(
            "SELECT valid_until FROM nodes WHERE id = ?",
            (neuron.id,),
        ).fetchone()
        assert row[0] == "2026-06-02T12:00:00+00:00"
    finally:
        conn.close()


def test_list_active_nodes_respects_temporal_window(brain_db) -> None:
    conn = connect(brain_db)
    try:
        old = create_neuron(
            conn,
            node_id="policy-v1",
            title="Policy v1",
            valid_from="2026-06-01T00:00:00+00:00",
        )
        conn.commit()

        supersede_neuron(
            conn,
            old.id,
            title="Policy v2",
            effective_at="2026-06-02T00:00:00+00:00",
        )
        conn.commit()

        active_now = list_active_nodes(conn, valid_at="2026-06-03T00:00:00+00:00")
        ids_now = {node.id for node in active_now}
        assert "policy-v1" not in ids_now
        assert any(node.title == "Policy v2" for node in active_now)

        active_past = list_active_nodes(conn, valid_at="2026-06-01T12:00:00+00:00")
        ids_past = {node.id for node in active_past}
        assert "policy-v1" in ids_past
    finally:
        conn.close()


def test_is_active_at_boundaries() -> None:
    from brainkm.services.memory import NeuronRecord

    record = NeuronRecord(
        id="n1",
        kind="memory",
        subtype="fact",
        title="t",
        content="c",
        valid_from="2026-06-01T10:00:00+00:00",
        valid_until="2026-06-02T10:00:00+00:00",
        session_id=None,
    )
    assert is_active_at(record, "2026-06-01T10:00:00+00:00") is True
    assert is_active_at(record, "2026-06-01T09:59:59+00:00") is False
    assert is_active_at(record, "2026-06-02T10:00:00+00:00") is False
    assert is_active_at(record, "2026-06-02T09:59:59+00:00") is True


def test_supersede_rejects_already_inactive_node(brain_db) -> None:
    conn = connect(brain_db)
    try:
        neuron = create_neuron(conn, node_id="inactive", title="Gone")
        conn.commit()
        forget_neuron(conn, neuron.id)
        conn.commit()

        with pytest.raises(ValueError, match="already inactive"):
            supersede_neuron(conn, neuron.id, title="Replacement")
    finally:
        conn.close()
