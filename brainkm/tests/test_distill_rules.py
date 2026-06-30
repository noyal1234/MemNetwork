"""Tests for rule-based distill adapter."""

from brainkm.adapters.distill_rules import RulesDistillAdapter, distill_round
from brainkm.models.distill import TranscriptMessage, TranscriptRound


def test_distill_round_extracts_decision() -> None:
    round_ = TranscriptRound(
        round_index=0,
        messages=(
            TranscriptMessage(
                role="user",
                text="We decided to use Zod instead of Yup for schema validation.",
                line_no=1,
            ),
        ),
    )
    neurons = distill_round(round_, chunk_ids=["chunk-1"])
    assert len(neurons) >= 1
    assert neurons[0].subtype == "decision"
    assert neurons[0].chunk_ids == ["chunk-1"]
    assert neurons[0].is_atomic()


def test_rules_adapter_respects_max_total() -> None:
    adapter = RulesDistillAdapter()
    rounds = tuple(
        TranscriptRound(
            round_index=i,
            messages=(
                TranscriptMessage(
                    role="user",
                    text=f"We decided to use approach {i} instead of legacy path {i}.",
                    line_no=i + 1,
                ),
            ),
        )
        for i in range(10)
    )
    round_chunk_ids = {i: [f"chunk-{i}"] for i in range(10)}
    neurons = adapter.distill_rounds(rounds, round_chunk_ids=round_chunk_ids, max_total=3)
    assert len(neurons) <= 3
