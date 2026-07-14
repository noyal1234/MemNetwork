"""Tests for the Groq distill adapter."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from brainkm.adapters.distill_prompts import SYSTEM_PROMPT
from brainkm.adapters.groq_distill import GroqDistillAdapter
from brainkm.db.connection import connect
from brainkm.models.brain_config import BrainConfig
from brainkm.models.distill import TranscriptMessage, TranscriptRound
from brainkm.services.memory import create_neuron


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
        def get(url: str, headers: dict | None = None, timeout: float = 0):
            if get_response is None:
                return _FakeResponse(status_code=200, payload={"data": []})
            if isinstance(get_response, Exception):
                raise get_response
            return get_response

        @staticmethod
        def post(url: str, json: dict, headers: dict | None = None, timeout: float = 0):
            if post_capture is not None:
                post_capture.append({"url": url, "json": json, "headers": headers})
            if post_response is None:
                return _FakeResponse(
                    status_code=200,
                    payload={"choices": [{"message": {"content": "[]"}}]},
                )
            if isinstance(post_response, Exception):
                raise post_response
            return post_response

    return _Httpx


def test_adapter_falls_back_without_api_key() -> None:
    cfg = BrainConfig(capture={"distill_mode": "groq"})
    # Empty string (not None) so env/.env GROQ_API_KEY cannot bypass the fallback path.
    adapter = GroqDistillAdapter(cfg, conn=None, api_key="")
    round_ = _make_round(
        "USER: We decided to use JWT instead of session cookies for API auth."
    )
    neurons = adapter.distill_rounds(
        (round_,),
        round_chunk_ids={0: ["chunk-1"]},
        max_total=10,
    )
    assert any(n.subtype == "decision" for n in neurons)


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

        cfg = BrainConfig(capture={"distill_mode": "groq"})
        adapter = GroqDistillAdapter(cfg, conn=conn, api_key="gsk_test_key")

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
        # Preflight chat probe + distill chat completion.
        distill_calls = [
            c for c in captured if (c.get("json") or {}).get("response_format")
        ]
        assert len(distill_calls) == 1
        payload = distill_calls[0]["json"]
        assert payload["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
        assert "Use JWT for API auth" in payload["messages"][1]["content"]
        assert payload["response_format"] == {"type": "json_object"}
        assert distill_calls[0]["headers"]["Authorization"] == "Bearer gsk_test_key"
        assert distill_calls[0]["url"].endswith("/chat/completions")
    finally:
        conn.close()


def test_adapter_parses_openai_style_response() -> None:
    cfg = BrainConfig(capture={"distill_mode": "groq"})
    adapter = GroqDistillAdapter(cfg, conn=None, api_key="gsk_test_key")

    response_content = json.dumps(
        {
            "neurons": [
                {
                    "subtype": "decision",
                    "title": "Use JWT for API auth",
                    "body": "Chose JWT over session cookies for API authentication.",
                    "tags": ["jwt", "auth"],
                }
            ]
        }
    )
    fake_httpx = _fake_httpx_module(
        post_response=_FakeResponse(
            status_code=200,
            payload={"choices": [{"message": {"content": response_content}}]},
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
    assert neurons[0].confidence == 0.8


def test_adapter_falls_back_when_unreachable() -> None:
    cfg = BrainConfig(capture={"distill_mode": "groq"})
    adapter = GroqDistillAdapter(cfg, conn=None, api_key="gsk_test_key")
    # Preflight is now chat/completions — a 500 on POST forces rules fallback.
    fake_httpx = _fake_httpx_module(post_response=_FakeResponse(status_code=500))
    round_ = _make_round(
        "USER: We decided to use JWT instead of session cookies for API auth."
    )

    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        neurons = adapter.distill_rounds(
            (round_,),
            round_chunk_ids={0: ["chunk-1"]},
            max_total=10,
        )

    assert any(n.subtype == "decision" for n in neurons)


def test_adapter_falls_back_on_rate_limit() -> None:
    cfg = BrainConfig(capture={"distill_mode": "groq"})
    adapter = GroqDistillAdapter(cfg, conn=None, api_key="gsk_test_key")
    fake_httpx = _fake_httpx_module(post_response=_FakeResponse(status_code=429))
    round_ = _make_round(
        "USER: We decided to use JWT instead of session cookies for API auth."
    )

    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        neurons = adapter.distill_rounds(
            (round_,),
            round_chunk_ids={0: ["chunk-1"]},
            max_total=10,
        )

    assert any(n.subtype == "decision" for n in neurons)


def test_adapter_falls_back_on_http_error() -> None:
    cfg = BrainConfig(capture={"distill_mode": "groq"})
    adapter = GroqDistillAdapter(cfg, conn=None, api_key="gsk_test_key")
    fake_httpx = _fake_httpx_module(post_response=RuntimeError("connection reset"))
    round_ = _make_round(
        "USER: We decided to use JWT instead of session cookies for API auth."
    )

    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        neurons = adapter.distill_rounds(
            (round_,),
            round_chunk_ids={0: ["chunk-1"]},
            max_total=10,
        )

    assert any(n.subtype == "decision" for n in neurons)
