"""Optional LLMLingua-2 path — fail-open when deps/model unavailable."""

from __future__ import annotations

import time

from brainkm.services.compression.types import StageResult
from brainkm.services.memory import token_count


def try_llmlingua(text: str, *, rate: float = 0.5) -> StageResult:
    """Attempt ML prompt compression; return original on any failure."""
    t0 = time.perf_counter()
    tokens_in = token_count(text)
    try:
        from llmlingua import PromptCompressor  # type: ignore[import-not-found]
    except Exception:
        return StageResult(
            engine_id="llmlingua2",
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_in,
            skipped_reason="optional_deps_missing",
            latency_ms=(time.perf_counter() - t0) * 1000.0,
        )

    try:
        compressor = PromptCompressor(
            model_name="microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank",
            use_llmlingua2=True,
        )
        result = compressor.compress_prompt(text, rate=rate, force_tokens=["\n", "?"])
        compressed = result.get("compressed_prompt") if isinstance(result, dict) else None
        if not compressed or not isinstance(compressed, str):
            raise RuntimeError("empty llmlingua result")
        return StageResult(
            engine_id="llmlingua2",
            text=compressed,
            tokens_in=tokens_in,
            tokens_out=token_count(compressed),
            latency_ms=(time.perf_counter() - t0) * 1000.0,
        )
    except Exception:
        return StageResult(
            engine_id="llmlingua2",
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_in,
            skipped_reason="fail_open",
            latency_ms=(time.perf_counter() - t0) * 1000.0,
        )
