"""Tests for end-to-end capture pipeline."""

import json
from pathlib import Path

from brainkm.db.connection import connect
from brainkm.models.brain_config import BrainConfig
from brainkm.services.capture import capture_transcript_file
from brainkm.services.review import pending_dir, reject_pending


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


def test_get_distill_adapter_selects_groq_mode() -> None:
    from brainkm.adapters.distill import get_distill_adapter
    from brainkm.adapters.groq_distill import GroqDistillAdapter

    adapter = get_distill_adapter(BrainConfig(capture={"distill_mode": "groq"}))
    assert isinstance(adapter, GroqDistillAdapter)


def test_get_distill_adapter_ollama_mode_accepts_conn(brain_db: Path) -> None:
    from brainkm.adapters.distill import get_distill_adapter
    from brainkm.adapters.ollama_distill import OllamaDistillAdapter
    from brainkm.db.connection import connect

    conn = connect(brain_db)
    try:
        adapter = get_distill_adapter(
            BrainConfig(capture={"distill_mode": "ollama"}),
            conn=conn,
        )
        assert isinstance(adapter, OllamaDistillAdapter)
    finally:
        conn.close()


def test_get_distill_adapter_groq_mode_accepts_conn(brain_db: Path) -> None:
    from brainkm.adapters.distill import get_distill_adapter
    from brainkm.adapters.groq_distill import GroqDistillAdapter
    from brainkm.db.connection import connect

    conn = connect(brain_db)
    try:
        adapter = get_distill_adapter(
            BrainConfig(capture={"distill_mode": "groq"}),
            conn=conn,
        )
        assert isinstance(adapter, GroqDistillAdapter)
    finally:
        conn.close()


def test_low_confidence_neuron_enqueued(brain_db, tmp_path: Path) -> None:
    transcript = tmp_path / "session-low.jsonl"
    _write_sample_transcript(transcript)
    config = BrainConfig(
        capture={"distill_mode": "rules"},
        learning={"auto_capture_confidence": 0.60},
    )
    result = capture_transcript_file(
        transcript,
        config=config,
        db_path=brain_db,
        session_id="session-low",
    )
    assert result.skipped is False
    pending = list(pending_dir(tmp_path).glob("*.json"))
    assert pending


def test_high_confidence_not_enqueued(brain_db, tmp_path: Path) -> None:
    transcript = tmp_path / "session-high.jsonl"
    _write_sample_transcript(transcript)
    config = BrainConfig(
        capture={"distill_mode": "rules"},
        learning={"auto_capture_confidence": 0.40},
    )
    result = capture_transcript_file(
        transcript,
        config=config,
        db_path=brain_db,
        session_id="session-high",
    )
    assert result.skipped is False
    pending = list(pending_dir(tmp_path).glob("*.json"))
    assert pending == []


def test_review_reject_soft_archives(brain_db, tmp_path: Path) -> None:
    transcript = tmp_path / "session-reject.jsonl"
    _write_sample_transcript(transcript)
    config = BrainConfig(
        capture={"distill_mode": "rules"},
        learning={"auto_capture_confidence": 0.60},
    )
    capture_transcript_file(
        transcript,
        config=config,
        db_path=brain_db,
        session_id="session-reject",
    )
    pending = list(pending_dir(tmp_path).glob("*.json"))
    assert pending, "expected at least one neuron in the review queue"
    node_id = pending[0].stem
    conn = connect(brain_db)
    try:
        assert reject_pending(node_id, conn=conn, project_dir=tmp_path) is True
        archived = conn.execute("SELECT valid_until FROM nodes WHERE id = ?", (node_id,)).fetchone()
        assert archived is not None
        assert archived["valid_until"] is not None
    finally:
        conn.close()
