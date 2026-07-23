"""MCP distill adapter: fake sampling vs rules fallback."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from brainkm.adapters.mcp_distill import (
    McpDistillAdapter,
    clear_sampling_callback,
    set_sampling_callback,
)
from brainkm.models.brain_config import BrainConfig
from brainkm.models.distill import TranscriptMessage, TranscriptRound
from brainkm.models.schemas import SessionStatusRequest


def _rounds() -> tuple[TranscriptRound, ...]:
    msg = TranscriptMessage(role="user", text="We chose JWT auth for APIs.", line_no=1)
    return (TranscriptRound(round_index=0, messages=(msg,)),)


def _two_rounds() -> tuple[TranscriptRound, ...]:
    r0 = TranscriptRound(
        round_index=0,
        messages=(TranscriptMessage(role="user", text="Chose SQLite for the brain.", line_no=1),),
    )
    r1 = TranscriptRound(
        round_index=1,
        messages=(
            TranscriptMessage(role="user", text="Prefer FTS5 over vectors by default.", line_no=2),
        ),
    )
    return (r0, r1)


def test_mcp_distill_no_callback_uses_rules() -> None:
    clear_sampling_callback()
    neurons = McpDistillAdapter(BrainConfig()).distill_rounds(
        _rounds(),
        round_chunk_ids={0: ["c1"]},
        max_total=5,
    )
    assert isinstance(neurons, list)
    assert len(neurons) >= 1
    assert all(n.chunk_ids == ["c1"] for n in neurons)


def test_mcp_distill_fake_callback() -> None:
    clear_sampling_callback()

    def fake(*, system: str, user: str, max_tokens: int = 2000) -> str:
        _ = (system, user, max_tokens)
        return (
            '[{"subtype":"decision","title":"JWT Auth","body":"Use JWT for APIs","tags":["auth"]}]'
        )

    set_sampling_callback(fake)
    try:
        neurons = McpDistillAdapter(BrainConfig()).distill_rounds(
            _rounds(),
            round_chunk_ids={0: ["c1"]},
            max_total=5,
        )
        assert any(n.title == "JWT Auth" for n in neurons)
        assert all(n.chunk_ids == ["c1"] for n in neurons if n.title == "JWT Auth")
    finally:
        clear_sampling_callback()


def test_mcp_distill_empty_callback_falls_back() -> None:
    clear_sampling_callback()
    set_sampling_callback(lambda **_: "")
    try:
        neurons = McpDistillAdapter(BrainConfig()).distill_rounds(
            _rounds(),
            round_chunk_ids={0: ["c1"]},
            max_total=5,
        )
        assert isinstance(neurons, list)
        assert len(neurons) >= 1
        assert all(n.chunk_ids == ["c1"] for n in neurons)
    finally:
        clear_sampling_callback()


def test_mcp_distill_respects_max_total() -> None:
    clear_sampling_callback()

    def fake(*, system: str, user: str, max_tokens: int = 2000) -> str:
        _ = (system, user, max_tokens)
        return (
            '[{"subtype":"fact","title":"A","body":"body a"},'
            '{"subtype":"fact","title":"B","body":"body b"},'
            '{"subtype":"fact","title":"C","body":"body c"}]'
        )

    set_sampling_callback(fake)
    try:
        neurons = McpDistillAdapter(BrainConfig()).distill_rounds(
            _rounds(),
            round_chunk_ids={0: ["c1"]},
            max_total=2,
        )
        assert len(neurons) <= 2
    finally:
        clear_sampling_callback()


def test_mcp_distill_per_round_chunk_ids() -> None:
    clear_sampling_callback()
    calls: list[str] = []

    def fake(*, system: str, user: str, max_tokens: int = 2000) -> str:
        _ = (system, max_tokens)
        calls.append(user)
        if "SQLite" in user:
            return '[{"subtype":"decision","title":"SQLite","body":"Local SQLite brain"}]'
        return '[{"subtype":"rule","title":"FTS5","body":"Default to FTS5 BM25"}]'

    set_sampling_callback(fake)
    try:
        neurons = McpDistillAdapter(BrainConfig()).distill_rounds(
            _two_rounds(),
            round_chunk_ids={0: ["c0"], 1: ["c1"]},
            max_total=5,
        )
        by_title = {n.title: n for n in neurons}
        assert by_title["SQLite"].chunk_ids == ["c0"]
        assert by_title["FTS5"].chunk_ids == ["c1"]
        assert len(calls) == 2
    finally:
        clear_sampling_callback()


def test_mcp_distill_empty_parse_falls_back_per_round() -> None:
    clear_sampling_callback()
    set_sampling_callback(lambda **_: "[]")
    try:
        neurons = McpDistillAdapter(BrainConfig()).distill_rounds(
            _rounds(),
            round_chunk_ids={0: ["c1"]},
            max_total=5,
        )
        assert len(neurons) >= 1  # rules fallback for empty parse
        assert all(n.chunk_ids == ["c1"] for n in neurons)
    finally:
        clear_sampling_callback()


def test_session_status_xor_rejected() -> None:
    with pytest.raises(ValidationError):
        SessionStatusRequest(title="only title")
    with pytest.raises(ValidationError):
        SessionStatusRequest(body="only body")
    SessionStatusRequest(title="t", body="b")
    SessionStatusRequest()
