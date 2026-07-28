"""Tests for services/memory.py neuron helpers."""

from __future__ import annotations

from pathlib import Path

from brainkm.db.connection import connect
from brainkm.services.compression.dual_store import get_compressed_view, put_compressed_view
from brainkm.services.compression.pipeline import ENGINE_VERSION
from brainkm.services.memory import (
    create_neuron,
    forget_neuron,
    recent_neuron_context,
    supersede_neuron,
)


def test_recent_neuron_context_returns_most_recent_first(brain_db: Path) -> None:
    conn = connect(brain_db)
    try:
        create_neuron(
            conn,
            title="Use JWT for API auth",
            content="Chose JWT over session cookies.",
            subtype="decision",
            tags=["jwt", "auth"],
            node_id="n1",
        )
        create_neuron(
            conn,
            title="Never store API keys in neurons",
            content="API keys must not be persisted.",
            subtype="rule",
            tags=["security"],
            node_id="n2",
        )
        conn.commit()

        context = recent_neuron_context(conn, limit=5)
        assert [item.title for item in context] == [
            "Never store API keys in neurons",
            "Use JWT for API auth",
        ]
        assert context[0].subtype == "rule"
        assert context[0].tags == ["security"]
        assert context[1].tags == ["jwt", "auth"]
    finally:
        conn.close()


def test_recent_neuron_context_excludes_context_subtype(brain_db: Path) -> None:
    conn = connect(brain_db)
    try:
        create_neuron(
            conn,
            title="Working on auth module",
            subtype="context",
            node_id="n1",
        )
        create_neuron(
            conn,
            title="Use JWT for API auth",
            subtype="decision",
            node_id="n2",
        )
        conn.commit()

        context = recent_neuron_context(conn, limit=5)
        assert [item.title for item in context] == ["Use JWT for API auth"]
    finally:
        conn.close()


def test_recent_neuron_context_excludes_archived(brain_db: Path) -> None:
    conn = connect(brain_db)
    try:
        create_neuron(conn, title="Old decision", subtype="decision", node_id="n1")
        conn.commit()
        forget_neuron(conn, "n1", reason="superseded")
        conn.commit()

        context = recent_neuron_context(conn, limit=5)
        assert context == []
    finally:
        conn.close()


def test_recent_neuron_context_respects_limit(brain_db: Path) -> None:
    conn = connect(brain_db)
    try:
        for index in range(3):
            create_neuron(
                conn,
                title=f"Decision {index}",
                subtype="decision",
                node_id=f"n{index}",
            )
        conn.commit()

        context = recent_neuron_context(conn, limit=2)
        assert len(context) == 2
    finally:
        conn.close()


def test_recent_neuron_context_empty_db(brain_db: Path) -> None:
    conn = connect(brain_db)
    try:
        assert recent_neuron_context(conn, limit=5) == []
    finally:
        conn.close()


def test_supersede_neuron_invalidates_cached_compressed_view(brain_db: Path) -> None:
    conn = connect(brain_db)
    try:
        create_neuron(conn, title="Old decision", content="Chose A over B.", subtype="decision", node_id="n1")
        conn.commit()
        put_compressed_view(
            conn,
            neuron_id="n1",
            full_body="Chose A over B.",
            compressed_text="A over B.",
            engine_version=ENGINE_VERSION,
            intensity="lite",
        )
        conn.commit()
        assert (
            get_compressed_view(
                conn,
                neuron_id="n1",
                full_body="Chose A over B.",
                engine_version=ENGINE_VERSION,
                intensity="lite",
            )
            == "A over B."
        )

        supersede_neuron(conn, "n1", title="New decision", content="Chose C instead.")
        conn.commit()

        assert (
            get_compressed_view(
                conn,
                neuron_id="n1",
                full_body="Chose A over B.",
                engine_version=ENGINE_VERSION,
                intensity="lite",
            )
            is None
        )
    finally:
        conn.close()


def test_forget_neuron_invalidates_cached_compressed_view(brain_db: Path) -> None:
    conn = connect(brain_db)
    try:
        create_neuron(conn, title="Stale fact", content="This will be forgotten.", node_id="n1")
        conn.commit()
        put_compressed_view(
            conn,
            neuron_id="n1",
            full_body="This will be forgotten.",
            compressed_text="Forgotten.",
            engine_version=ENGINE_VERSION,
            intensity="lite",
        )
        conn.commit()

        forget_neuron(conn, "n1")
        conn.commit()

        assert (
            get_compressed_view(
                conn,
                neuron_id="n1",
                full_body="This will be forgotten.",
                engine_version=ENGINE_VERSION,
                intensity="lite",
            )
            is None
        )
    finally:
        conn.close()
