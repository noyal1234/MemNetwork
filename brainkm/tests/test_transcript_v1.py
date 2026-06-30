"""Tests for Cursor transcript JSONL parsing."""

import json
from pathlib import Path

from brainkm.adapters.transcript_v1 import (
    CURSOR_V1_MAGIC,
    detect_transcript_format,
    parse_raw_text,
    parse_transcript_file,
)


def test_detect_cursor_v1_from_role_message_shape() -> None:
    line = json.dumps({"role": "user", "message": {"content": [{"type": "text", "text": "hi"}]}})
    assert detect_transcript_format([line]) == CURSOR_V1_MAGIC


def test_detect_explicit_magic_format() -> None:
    line = json.dumps({"transcriptFormat": CURSOR_V1_MAGIC, "role": "user", "message": {}})
    assert detect_transcript_format([line]) == CURSOR_V1_MAGIC


def test_detect_raw_text_fallback() -> None:
    assert detect_transcript_format(["plain text without json"]) == "raw_text"


def test_parse_transcript_file_decomposes_rounds(tmp_path: Path) -> None:
    transcript = tmp_path / "sess-abc.jsonl"
    rows = [
        {
            "role": "user",
            "message": {"content": [{"type": "text", "text": "We decided to use JWT."}]},
        },
        {
            "role": "assistant",
            "message": {
                "content": [{"type": "text", "text": "JWT access tokens expire after 15 minutes."}]
            },
        },
        {
            "role": "user",
            "message": {"content": [{"type": "text", "text": "Next: payment integration."}]},
        },
    ]
    transcript.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    parsed = parse_transcript_file(transcript)
    assert parsed.format_name == CURSOR_V1_MAGIC
    assert len(parsed.messages) == 3
    assert len(parsed.rounds) == 2
    assert "JWT" in parsed.rounds[0].combined_text


def test_parse_raw_text_fallback_parser() -> None:
    parsed = parse_raw_text("First paragraph.\n\nSecond paragraph.", session_id="raw-1")
    assert parsed.format_name == "raw_text"
    assert len(parsed.messages) == 2
