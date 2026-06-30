"""Tests for PreCompact handover service and CLI."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from brainkm.cli import app
from brainkm.db.connection import connect
from brainkm.models.brain_config import BrainConfig
from brainkm.services.handover import (
    parse_precompact_hook_payload,
    run_handover,
    run_handover_from_stdin,
)


def _write_handover_transcript(path: Path) -> None:
    rows = [
        {
            "role": "user",
            "message": {
                "content": [
                    {
                        "type": "text",
                        "text": "We decided to use SQLite with WAL mode for the project brain.",
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
                        "text": "Never disable foreign keys on brain.db connections.",
                    }
                ]
            },
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_parse_precompact_hook_payload_resolves_relative_path(tmp_path: Path) -> None:
    transcript = tmp_path / "sess.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    payload = parse_precompact_hook_payload(
        json.dumps({"transcript_path": "sess.jsonl", "session_id": "sess-1"}),
        cwd=tmp_path,
    )
    assert payload.transcript_path == transcript
    assert payload.session_id == "sess-1"


def test_parse_precompact_hook_payload_requires_transcript_path() -> None:
    with pytest.raises(ValueError, match="transcript_path"):
        parse_precompact_hook_payload("{}")


def test_handover_persists_neurons_and_checkpoints(brain_db, tmp_path: Path) -> None:
    transcript = tmp_path / "handover-1.jsonl"
    _write_handover_transcript(transcript)

    config = BrainConfig(
        capture={"distill_mode": "rules"},
        handover={"export_markdown": True},
    )
    result = run_handover(
        transcript,
        project_dir=tmp_path,
        config=config,
        db_path=brain_db,
        session_id="handover-1",
    )

    assert result.skipped is False
    assert result.checkpoint_ok is True
    assert result.neuron_count >= 1
    assert result.export_path is not None
    assert result.export_path.name.startswith("HANDOVER-")
    assert result.export_path.exists()

    conn = connect(brain_db)
    try:
        neuron_count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        assert neuron_count >= 1
    finally:
        conn.close()


def test_handover_does_not_skip_duplicate_fingerprint(brain_db, tmp_path: Path) -> None:
    transcript = tmp_path / "handover-dup.jsonl"
    _write_handover_transcript(transcript)
    config = BrainConfig(capture={"distill_mode": "rules"}, handover={"export_markdown": False})

    first = run_handover(
        transcript, project_dir=tmp_path, config=config, db_path=brain_db, session_id="dup"
    )
    second = run_handover(
        transcript, project_dir=tmp_path, config=config, db_path=brain_db, session_id="dup"
    )

    assert first.skipped is False
    assert second.skipped is False


def test_handover_from_stdin(brain_db, tmp_path: Path) -> None:
    transcript = tmp_path / "stdin-session.jsonl"
    _write_handover_transcript(transcript)
    config = BrainConfig(capture={"distill_mode": "rules"}, handover={"export_markdown": False})
    payload = json.dumps(
        {
            "transcript_path": str(transcript),
            "session_id": "stdin-session",
        }
    )

    result = run_handover_from_stdin(payload, project_dir=tmp_path, config=config)
    assert result.checkpoint_ok is True
    assert result.session_id == "stdin-session"


def test_handover_cli_exits_nonzero_on_checkpoint_failure(
    brain_db,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transcript = tmp_path / "cli-session.jsonl"
    _write_handover_transcript(transcript)

    from brainkm.db import checkpoint as checkpoint_mod

    def _fail_checkpoint(conn, **kwargs):
        return checkpoint_mod.CheckpointResult(
            ok=False,
            busy=1,
            log_frames=3,
            checkpointed_frames=1,
            attempts=10,
        )

    monkeypatch.setattr("brainkm.services.handover.wal_checkpoint", _fail_checkpoint)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "handover",
            str(transcript),
            "--session-id",
            "cli-session",
            "--project-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    assert "WAL checkpoint failed" in result.output


def test_handover_respects_precompact_disabled(brain_db, tmp_path: Path) -> None:
    transcript = tmp_path / "disabled.jsonl"
    _write_handover_transcript(transcript)
    config = BrainConfig(handover={"precompact_enabled": False})

    result = run_handover(transcript, project_dir=tmp_path, config=config, db_path=brain_db)
    assert result.skipped is True
    assert result.reason == "precompact disabled"
    assert result.checkpoint_ok is True
