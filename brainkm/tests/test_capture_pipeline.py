"""Tests for end-to-end capture pipeline."""

import json
from pathlib import Path

from brainkm.db.connection import connect
from brainkm.models.brain_config import BrainConfig
from brainkm.services.capture import capture_transcript_file


def _write_sample_transcript(path: Path) -> None:
    rows = [
        {
            "role": "user",
            "message": {
                "content": [
                    {
                        "type": "text",
                        "text": "We decided to use JWT instead of session cookies for API auth.",
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
                        "text": (
                            "Never store API keys in neurons. "
                            "Access tokens expire after 15 minutes."
                        ),
                    }
                ]
            },
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_capture_pipeline_persists_chunks_neurons_and_provenance(brain_db, tmp_path: Path) -> None:
    transcript = tmp_path / "session-1.jsonl"
    _write_sample_transcript(transcript)

    config = BrainConfig(capture={"distill_mode": "rules"})
    result = capture_transcript_file(
        transcript,
        config=config,
        db_path=brain_db,
        session_id="session-1",
    )

    assert result.skipped is False
    assert result.chunk_count == 2
    assert result.neuron_count >= 1

    conn = connect(brain_db)
    try:
        chunk_count = conn.execute("SELECT COUNT(*) FROM session_chunks").fetchone()[0]
        neuron_count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        link_count = conn.execute("SELECT COUNT(*) FROM chunk_sources").fetchone()[0]
        ingested = conn.execute(
            "SELECT distill_mode, neuron_count FROM ingested_sessions WHERE session_id = ?",
            ("session-1",),
        ).fetchone()

        assert chunk_count == 2
        assert neuron_count >= 1
        assert link_count >= 1
        assert ingested[0] == "rules"
        assert ingested[1] == result.neuron_count
    finally:
        conn.close()


def test_capture_skips_duplicate_fingerprint(brain_db, tmp_path: Path) -> None:
    transcript = tmp_path / "session-dup.jsonl"
    _write_sample_transcript(transcript)
    config = BrainConfig(capture={"distill_mode": "rules"})

    first = capture_transcript_file(transcript, config=config, db_path=brain_db)
    second = capture_transcript_file(transcript, config=config, db_path=brain_db)

    assert first.skipped is False
    assert second.skipped is True
    assert second.reason == "duplicate fingerprint"


def test_get_distill_adapter_selects_cursor_mode() -> None:
    from brainkm.adapters.cursor_distill import CursorDistillAdapter
    from brainkm.adapters.distill import get_distill_adapter

    adapter = get_distill_adapter(BrainConfig(capture={"distill_mode": "cursor"}))
    assert isinstance(adapter, CursorDistillAdapter)


def test_get_distill_adapter_selects_ollama_mode() -> None:
    from brainkm.adapters.distill import get_distill_adapter
    from brainkm.adapters.ollama_distill import OllamaDistillAdapter

    adapter = get_distill_adapter(BrainConfig(capture={"distill_mode": "ollama"}))
    assert isinstance(adapter, OllamaDistillAdapter)
