"""Claude Code JSONL transcript parsing."""

from __future__ import annotations

from pathlib import Path

from brainkm.adapters.transcript_v1 import (
    CLAUDE_JSONL,
    detect_transcript_format,
    parse_transcript_file,
)


def test_detect_claude_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "claude.jsonl"
    path.write_text(
        '{"type":"user","message":{"role":"user","content":"Why JWT?"}}\n'
        '{"type":"assistant","message":{"role":"assistant","content":'
        '[{"type":"text","text":"We chose JWT."}]}}\n',
        encoding="utf-8",
    )
    lines = path.read_text().splitlines()
    assert detect_transcript_format(lines) == CLAUDE_JSONL
    parsed = parse_transcript_file(path)
    assert parsed.format_name == CLAUDE_JSONL
    assert len(parsed.messages) >= 2
    assert parsed.messages[0].role == "user"
    assert "JWT" in parsed.messages[0].text
    assert parsed.rounds


def test_claude_human_maps_to_user(tmp_path: Path) -> None:
    path = tmp_path / "h.jsonl"
    path.write_text(
        '{"type":"human","message":{"role":"human","content":"hello"}}\n',
        encoding="utf-8",
    )
    parsed = parse_transcript_file(path)
    assert parsed.format_name == CLAUDE_JSONL
    assert parsed.messages[0].role == "user"
