"""MCP distill adapter: fake sampling vs rules fallback."""

from __future__ import annotations

from brainkm.adapters.mcp_distill import (
    McpDistillAdapter,
    clear_sampling_callback,
    set_sampling_callback,
)
from brainkm.models.brain_config import BrainConfig
from brainkm.models.distill import TranscriptMessage, TranscriptRound


def _rounds() -> tuple[TranscriptRound, ...]:
    msg = TranscriptMessage(role="user", text="We chose JWT auth for APIs.", line_no=1)
    return (TranscriptRound(round_index=0, messages=(msg,)),)


def test_mcp_distill_no_callback_uses_rules() -> None:
    clear_sampling_callback()
    neurons = McpDistillAdapter(BrainConfig()).distill_rounds(
        _rounds(),
        round_chunk_ids={0: ["c1"]},
        max_total=5,
    )
    assert isinstance(neurons, list)


def test_mcp_distill_fake_callback() -> None:
    clear_sampling_callback()

    def fake(*, system: str, user: str, max_tokens: int = 2000) -> str:
        _ = (system, user, max_tokens)
        return (
            '[{"subtype":"decision","title":"JWT Auth",'
            '"body":"Use JWT for APIs","tags":["auth"]}]'
        )

    set_sampling_callback(fake)
    try:
        neurons = McpDistillAdapter(BrainConfig()).distill_rounds(
            _rounds(),
            round_chunk_ids={0: ["c1"]},
            max_total=5,
        )
        assert any(n.title == "JWT Auth" for n in neurons)
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
    finally:
        clear_sampling_callback()
