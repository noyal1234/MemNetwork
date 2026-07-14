"""Tests for Cursor distill cleaning and adapter."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from brainkm.adapters.cursor_clean import clean_cursor_text, distillable_round
from brainkm.adapters.cursor_distill import (
    CursorDistillAdapter,
    distill_cursor_round,
    load_predistilled_neurons,
    pending_cursor_distill_path,
)
from brainkm.models.brain_config import BrainConfig
from brainkm.models.distill import TranscriptMessage, TranscriptRound
from brainkm.services.quality import passes_quality_gate


def _round(*texts: tuple[str, str]) -> TranscriptRound:
    messages = tuple(
        TranscriptMessage(role=role, text=text, line_no=index + 1)
        for index, (role, text) in enumerate(texts)
    )
    return TranscriptRound(round_index=0, messages=messages)


def test_clean_cursor_text_extracts_user_query() -> None:
    raw = (
        "<timestamp>Tuesday, Jul 14, 2026</timestamp>\n"
        "<user_query>\nWe decided to use JWT instead of cookies.\n</user_query>"
    )
    assert clean_cursor_text(raw) == "We decided to use JWT instead of cookies."


def test_clean_cursor_text_strips_tool_use() -> None:
    raw = "[tool_use:Shell]\n[tool_use:Read]\nNever store API keys in neurons."
    assert clean_cursor_text(raw) == "Never store API keys in neurons."


def test_distillable_round_drops_tool_noise() -> None:
    round_ = _round(
        ("assistant", "[tool_use:Shell]\n[tool_use:Read]"),
        ("assistant", "Never store API keys in neurons."),
    )
    cleaned = distillable_round(round_)
    assert cleaned is not None
    assert len(cleaned.messages) == 1
    assert "Never store API keys" in cleaned.messages[0].text


def test_distill_cursor_round_extracts_decision_without_chrome() -> None:
    round_ = _round(
        (
            "user",
            "<timestamp>now</timestamp><user_query>We decided to use Zod instead of Yup.</user_query>",
        ),
        ("assistant", "[tool_use:Write]\nGot it — Zod is the validation library."),
    )
    neurons = distill_cursor_round(round_, chunk_ids=["c1"])
    assert neurons
    assert all("user_query" not in n.title.lower() for n in neurons)
    assert all("[tool_use" not in n.body.lower() for n in neurons)
    assert any(n.subtype == "decision" for n in neurons)
    assert all(passes_quality_gate(n) for n in neurons)


def test_quality_gate_rejects_transcript_chrome() -> None:
    from brainkm.models.distill import DistilledNeuron

    junk = DistilledNeuron(
        subtype="fact",
        title="USER: <user_query> Please revert",
        body="USER: <user_query> Please revert the changes",
        tags=[],
    )
    assert passes_quality_gate(junk) is False


def test_adapter_uses_predistilled_json(tmp_path: Path) -> None:
    session_id = "sess-pre"
    path = pending_cursor_distill_path(tmp_path, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [
                {
                    "subtype": "decision",
                    "title": "Use JWT for API auth",
                    "body": "Chose JWT over session cookies for API authentication.",
                    "tags": ["jwt", "auth"],
                }
            ]
        ),
        encoding="utf-8",
    )
    loaded = load_predistilled_neurons(tmp_path, session_id, chunk_ids=["c1"])
    assert loaded is not None
    assert loaded[0].title == "Use JWT for API auth"

    cfg = BrainConfig(capture={"distill_mode": "cursor"})
    adapter = CursorDistillAdapter(
        cfg,
        project_dir=tmp_path,
        session_id=session_id,
        agent_bin=None,
    )
    neurons = adapter.distill_rounds(
        (_round(("user", "ignored raw text that would otherwise distill poorly"),)),
        round_chunk_ids={0: ["c1"]},
        max_total=10,
    )
    assert len(neurons) == 1
    assert neurons[0].title == "Use JWT for API auth"
    assert neurons[0].confidence >= 0.8


def test_adapter_falls_back_to_heuristic_without_agent() -> None:
    cfg = BrainConfig(capture={"distill_mode": "cursor"})
    adapter = CursorDistillAdapter(cfg, agent_bin=None)
    round_ = _round(
        ("user", "We decided to use SQLite instead of Postgres for V1."),
    )
    neurons = adapter.distill_rounds(
        (round_,),
        round_chunk_ids={0: ["chunk-1"]},
        max_total=5,
    )
    assert neurons
    assert neurons[0].subtype == "decision"
    assert "SQLite" in neurons[0].body
    assert neurons[0].confidence >= 0.65


def test_adapter_agent_cli_parses_json() -> None:
    cfg = BrainConfig(capture={"distill_mode": "cursor"})
    adapter = CursorDistillAdapter(cfg, agent_bin="/fake/agent")
    payload = json.dumps(
        [
            {
                "subtype": "rule",
                "title": "Never store API keys in neurons",
                "body": "API keys must not be persisted in project memory.",
                "tags": ["security"],
            }
        ]
    )

    class _Completed:
        returncode = 0
        stdout = payload
        stderr = ""

    with patch("brainkm.adapters.cursor_distill.subprocess.run", return_value=_Completed()):
        round_ = _round(("user", "Never store API keys in neurons."))
        neurons = adapter.distill_rounds(
            (round_,),
            round_chunk_ids={0: ["c1"]},
            max_total=5,
        )
    assert len(neurons) == 1
    assert neurons[0].subtype == "rule"
    assert neurons[0].confidence == 0.85
