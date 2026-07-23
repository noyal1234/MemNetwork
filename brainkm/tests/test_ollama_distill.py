"""Tests for the Ollama distill adapter prompt, context injection, and chat call."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from brainkm.adapters.distill_prompts import SYSTEM_PROMPT, build_context_block
from brainkm.adapters.ollama_distill import OllamaDistillAdapter
from brainkm.db.connection import connect
from brainkm.models.brain_config import BrainConfig
from brainkm.models.distill import TranscriptMessage, TranscriptRound
from brainkm.services.memory import create_neuron


def _build_context_block(*args, **kwargs):
    return build_context_block(*args, **kwargs)


def _make_round(text: str, *, index: int = 0) -> TranscriptRound:
    return TranscriptRound(
        round_index=index,
        messages=(TranscriptMessage(role="user", text=text, line_no=1),),
    )


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return self._payload


def _fake_httpx_module(*, get_response=None, post_response=None, post_capture: list | None = None):
    class _Httpx:
        @staticmethod
        def get(url: str, timeout: float):
            if get_response is None:
                return _FakeResponse(status_code=200)
            if isinstance(get_response, Exception):
                raise get_response
            return get_response

        @staticmethod
        def post(url: str, json: dict, timeout: float):
            if post_capture is not None:
                post_capture.append(json)
            if post_response is None:
                return _FakeResponse(status_code=200, payload={"message": {"content": "[]"}})
            if isinstance(post_response, Exception):
                raise post_response
            return post_response

    return _Httpx


def test_build_context_block_empty_without_conn() -> None:
    assert _build_context_block(None) == ""


def test_build_context_block_empty_when_no_neurons(brain_db: Path) -> None:
    conn = connect(brain_db)
    try:
        assert _build_context_block(conn) == ""
    finally:
        conn.close()


def test_build_context_block_formats_recent_neurons(brain_db: Path) -> None:
    conn = connect(brain_db)
    try:
        create_neuron(
            conn,
            title="Use JWT for API auth",
            subtype="decision",
            tags=["jwt", "auth"],
            node_id="n1",
        )
        conn.commit()

        block = _build_context_block(conn)
        assert "Recent project memory" in block
        assert "[decision] Use JWT for API auth (tags: jwt, auth)" in block
        assert block.endswith("\n\n")
    finally:
        conn.close()


def test_adapter_without_conn_has_empty_context() -> None:
    cfg = BrainConfig(capture={"distill_mode": "ollama"})
    adapter = OllamaDistillAdapter(cfg, conn=None)
    assert adapter._context_block == ""


def test_adapter_includes_context_in_chat_payload(brain_db: Path) -> None:
    conn = connect(brain_db)
    try:
        create_neuron(
            conn,
            title="Use JWT for API auth",
            subtype="decision",
            tags=["jwt"],
            node_id="n1",
        )
        conn.commit()

        cfg = BrainConfig(capture={"distill_mode": "ollama"})
        adapter = OllamaDistillAdapter(cfg, conn=conn)

        captured: list[dict] = []
        fake_httpx = _fake_httpx_module(post_capture=captured)
        round_ = _make_round("USER: We need to pick an auth strategy.")

        with patch.dict("sys.modules", {"httpx": fake_httpx}):
            neurons = adapter.distill_rounds(
                (round_,),
                round_chunk_ids={0: ["chunk-1"]},
                max_total=10,
            )

        assert neurons == []
        assert len(captured) == 1
        payload = captured[0]
        assert payload["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
        assert "Use JWT for API auth" in payload["messages"][1]["content"]
        assert "Round:\n" in payload["messages"][1]["content"]
    finally:
        conn.close()


def test_adapter_parses_chat_response() -> None:
    cfg = BrainConfig(capture={"distill_mode": "ollama"})
    adapter = OllamaDistillAdapter(cfg, conn=None)

    response_content = json.dumps(
        [
            {
                "subtype": "decision",
                "title": "Use JWT for API auth",
                "body": "Chose JWT over session cookies for API authentication.",
                "tags": ["jwt", "auth"],
            }
        ]
    )
    fake_httpx = _fake_httpx_module(
        post_response=_FakeResponse(
            status_code=200,
            payload={"message": {"content": response_content}},
        )
    )
    round_ = _make_round("USER: We decided to use JWT instead of session cookies.")

    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        neurons = adapter.distill_rounds(
            (round_,),
            round_chunk_ids={0: ["chunk-1"]},
            max_total=10,
        )

    assert len(neurons) == 1
    assert neurons[0].title == "Use JWT for API auth"
    assert neurons[0].subtype == "decision"
    assert neurons[0].confidence == 0.75


def test_adapter_falls_back_to_rules_when_unreachable() -> None:
    cfg = BrainConfig(capture={"distill_mode": "ollama"})
    adapter = OllamaDistillAdapter(cfg, conn=None)

    fake_httpx = _fake_httpx_module(get_response=_FakeResponse(status_code=500))
    round_ = _make_round("USER: We decided to use JWT instead of session cookies for API auth.")

    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        neurons = adapter.distill_rounds(
            (round_,),
            round_chunk_ids={0: ["chunk-1"]},
            max_total=10,
        )

    # Rules fallback should still extract the decision sentence.
    assert any(n.subtype == "decision" for n in neurons)


def test_adapter_falls_back_per_round_on_http_error() -> None:
    cfg = BrainConfig(capture={"distill_mode": "ollama"})
    adapter = OllamaDistillAdapter(cfg, conn=None)

    fake_httpx = _fake_httpx_module(post_response=RuntimeError("connection reset"))
    round_ = _make_round("USER: We decided to use JWT instead of session cookies for API auth.")

    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        neurons = adapter.distill_rounds(
            (round_,),
            round_chunk_ids={0: ["chunk-1"]},
            max_total=10,
        )

    assert any(n.subtype == "decision" for n in neurons)
