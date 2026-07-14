"""Regression tests for the token/memory/distill audit fix plan."""

from __future__ import annotations

import json

import pytest

from brainkm.adapters.distill_prompts import SYSTEM_PROMPT, normalize_subtype, parse_json_array
from brainkm.adapters.distill_rules import distill_round
from brainkm.db.connection import connect
from brainkm.models.brain_config import BrainConfig
from brainkm.models.distill import DistilledNeuron, TranscriptMessage, TranscriptRound
from brainkm.models.schemas import ContextPackRequest, RecallRequest
from brainkm.services.hygiene import purge_noisy_neurons
from brainkm.services.memory import token_count
from brainkm.services.quality import filter_distilled, passes_quality_gate
from brainkm.tools.dispatch import BrainRuntime, handle_context_pack, handle_recall
from tests.conftest import insert_node


@pytest.fixture
def runtime(tmp_path) -> BrainRuntime:
    from brainkm.db.migrate import migrate

    migrate(db_path=tmp_path / ".brain" / "brain.db", run_integrity_check=True)
    return BrainRuntime(project_dir=tmp_path)


def test_dirty_cursor_round_yields_no_noise_neurons() -> None:
    round_ = TranscriptRound(
        round_index=0,
        messages=(
            TranscriptMessage(
                role="user",
                text="<timestamp>Tue</timestamp><user_query>hello</user_query>",
                line_no=1,
            ),
            TranscriptMessage(
                role="assistant",
                text="[tool_use:Read]\n[tool_use:Grep]\nI'll map the scheduler next.",
                line_no=2,
            ),
        ),
    )
    neurons = distill_round(round_, chunk_ids=["c1"])
    assert neurons == []


def test_quality_gate_rejects_chrome_and_tool_spam() -> None:
    bad = [
        DistilledNeuron(
            subtype="error",
            title="[tool_use:Read] ASSISTANT spam",
            body="[tool_use:Read]\n[tool_use:Grep]\nIt failed.",
        ),
        DistilledNeuron(
            subtype="fact",
            title="USER: <timestamp>x</timestamp>",
            body="<user_query>Do you think this is best?</user_query>",
        ),
        DistilledNeuron(
            subtype="decision",
            title="I'll map the scheduler next",
            body="I'll map the scheduler, config, and ignore paths so the plan covers wiring.",
        ),
        DistilledNeuron(
            subtype="decision",
            title="## What a normal session looks like",
            body="## What a normal session looks like with markdown headers everywhere.",
        ),
    ]
    for item in bad:
        assert passes_quality_gate(item) is False


def test_filter_distilled_dedupes_within_batch() -> None:
    items = [
        DistilledNeuron(subtype="decision", title="Use JWT", body="Chose JWT over cookies for auth."),
        DistilledNeuron(subtype="decision", title="Use JWT", body="Chose JWT over cookies for auth."),
    ]
    accepted = filter_distilled(items, max_count=10)
    assert len(accepted) == 1


def test_normalize_subtype_rejects_unknown() -> None:
    assert normalize_subtype("decision") == "decision"
    assert normalize_subtype("pattern") is None
    assert normalize_subtype(None) == "fact"


def test_system_prompt_uses_neurons_wrapper() -> None:
    assert '{"neurons":' in SYSTEM_PROMPT.replace(" ", "")
    body = "B" * 20
    parsed = parse_json_array(
        json.dumps({"neurons": [{"subtype": "fact", "title": "T", "body": body}]})
    )
    assert len(parsed) == 1


def test_context_pack_mcp_payload_under_budget(runtime, tmp_path) -> None:
    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        for i in range(30):
            insert_node(
                conn,
                node_id=f"d{i}",
                subtype="decision",
                title=f"Decision about auth layer {i}",
                content=(
                    "Chose SQLite FTS5 for project memory recall and graph neighborhoods. "
                    "Keep packs bounded and prefer verify-in-source. " * 8
                ),
            )
        conn.commit()
        long_query = ("token budget context pack truncation decision auth sqlite " * 40).strip()
        result = handle_context_pack(
            conn,
            ContextPackRequest(query=long_query, session_id="s-cap"),
            config=BrainConfig(recall={"abstain_on_low_confidence": False}),
            project_dir=tmp_path,
        )
        assert result.neurons == []
        assert result.graph_nodes == []
        assert token_count(result.pack_text) <= BrainConfig().budget.total_tokens
        payload = json.dumps(result.model_dump(), separators=(",", ":"), ensure_ascii=False)
        assert token_count(payload) <= BrainConfig().budget.total_tokens
        assert len(result.query) <= 240
    finally:
        conn.close()


def test_context_pack_include_structured(runtime, tmp_path) -> None:
    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        insert_node(
            conn,
            node_id="d1",
            subtype="decision",
            title="Use FTS5",
            content="Prefer SQLite FTS5 for recall search.",
        )
        conn.commit()
        result = handle_context_pack(
            conn,
            ContextPackRequest(
                query="FTS5 recall",
                session_id="s-struct",
                include_structured=True,
            ),
            config=BrainConfig(recall={"abstain_on_low_confidence": False}),
            project_dir=tmp_path,
        )
        assert any(n.title == "Use FTS5" for n in result.neurons)
    finally:
        conn.close()


def test_recall_logs_mcp_activity(runtime, tmp_path) -> None:
    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        insert_node(
            conn,
            node_id="r1",
            subtype="decision",
            title="Token budget",
            content="Enforce token budget on context pack pack_text end to end.",
        )
        conn.commit()
        handle_recall(
            conn,
            RecallRequest(query="token budget context pack", session_id="s-rec"),
            config=BrainConfig(recall={"abstain_on_low_confidence": False}),
            project_dir=tmp_path,
        )
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM session_activity
            WHERE kind = 'tool_use' AND source IN ('mcp', 'mcp_abstained')
              AND tool_name LIKE 'recall%'
            """
        ).fetchone()
        assert int(row["n"]) >= 1
    finally:
        conn.close()


def test_hygiene_archives_noisy_neurons(runtime, tmp_path) -> None:
    conn = connect(tmp_path / ".brain" / "brain.db")
    try:
        insert_node(
            conn,
            node_id="good1",
            subtype="rule",
            title="MCP dispatch pattern",
            content="tools delegate to services; validate with Pydantic at entry",
        )
        insert_node(
            conn,
            node_id="bad1",
            subtype="error",
            title="[tool_use:Read] spam wall",
            content="[tool_use:Read]\n[tool_use:Grep]\nASSISTANT: It failed somehow.",
        )
        conn.commit()
        result = purge_noisy_neurons(conn, dry_run=False)
        assert result.archived >= 1
        archived = conn.execute(
            "SELECT valid_until FROM nodes WHERE id = 'bad1'"
        ).fetchone()
        assert archived["valid_until"] is not None
        kept = conn.execute(
            "SELECT valid_until FROM nodes WHERE id = 'good1'"
        ).fetchone()
        assert kept["valid_until"] is None
    finally:
        conn.close()
