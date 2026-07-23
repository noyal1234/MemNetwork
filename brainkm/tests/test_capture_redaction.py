"""Regression: capture/handover must not store secrets; blocked chunks skip."""

from __future__ import annotations

import json
from pathlib import Path

from brainkm.db.connection import connect
from brainkm.models.brain_config import BrainConfig
from brainkm.services.capture import capture_transcript_file
from brainkm.services.memory import create_neuron
from brainkm.services.repair import repair_brain, rescan_neurons_for_secrets


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_capture_skips_secret_chunk_and_continues(brain_db, tmp_path: Path) -> None:
    transcript = tmp_path / "secret-session.jsonl"
    _write_jsonl(
        transcript,
        [
            {
                "role": "user",
                "message": {
                    "content": [
                        {
                            "type": "text",
                            "text": "Use key sk-live-abcdefghijklmnopqrstuvwxyz123456 for staging",
                        }
                    ]
                },
            },
            {
                "role": "user",
                "message": {
                    "content": [
                        {
                            "type": "text",
                            "text": "We decided to use JWT instead of session cookies for API auth.",  # noqa: E501
                        }
                    ]
                },
            },
            {
                "role": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "text",
                            "text": "Access tokens expire after 15 minutes.",
                        }
                    ]
                },
            },
        ],
    )

    result = capture_transcript_file(
        transcript,
        config=BrainConfig(capture={"distill_mode": "rules"}),
        db_path=brain_db,
        session_id="secret-session",
    )

    assert result.skipped is False
    assert result.chunk_count == 2  # secret message skipped

    conn = connect(brain_db)
    try:
        chunks = [row[0] for row in conn.execute("SELECT content FROM session_chunks").fetchall()]
        assert all("sk-live-" not in text for text in chunks)
        secret_neurons = conn.execute(
            """
            SELECT COUNT(*) FROM nodes
            WHERE content LIKE '%sk-live-%' OR title LIKE '%sk-live-%'
            """
        ).fetchone()[0]
        assert secret_neurons == 0
        assert conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] >= 1
    finally:
        conn.close()


def test_capture_blocks_secret_in_distilled_neuron_title_body(brain_db, tmp_path: Path) -> None:
    """Even if distill somehow emits a secret, remember_neuron must block it."""
    from brainkm.adapters.redaction import RedactionBlockedError
    from brainkm.services.memory import remember_neuron

    conn = connect(brain_db)
    try:
        try:
            remember_neuron(
                conn,
                title="Staging key",
                content="sk-live-abcdefghijklmnopqrstuvwxyz123456",
                source="capture:rules",
            )
            raised = False
        except RedactionBlockedError:
            raised = True
        assert raised is True
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 0
    finally:
        conn.close()


def test_repair_rescan_archives_legacy_secret_neurons(brain_db, tmp_path: Path) -> None:
    project = tmp_path
    # brain_db is under tmp_path/.brain/brain.db from fixture — use create_neuron
    # to simulate the pre-fix unredacted path.
    conn = connect(brain_db)
    try:
        create_neuron(
            conn,
            title="Leaked key",
            content="sk-live-abcdefghijklmnopqrstuvwxyz123456",
            kind="memory",
            subtype="fact",
            source="capture:rules",
        )
        conn.commit()
        archived = rescan_neurons_for_secrets(conn)
        conn.commit()
        assert archived == 1
        active = conn.execute("SELECT COUNT(*) FROM nodes WHERE valid_until IS NULL").fetchone()[0]
        assert active == 0
    finally:
        conn.close()

    result = repair_brain(project_dir=project, recalibrate_abstention=False)
    assert result.integrity_ok is True
