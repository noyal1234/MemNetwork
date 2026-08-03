# Pack-vs-dump proxy (Antigravity-themed scenarios)

> **Generated:** 2026-07-31 16:31:51 UTC  
> **Mode:** `tokens-only`  
> **LLM driver:** `none` (local sizes only)  
> **brainkm:** 0.9.0 · live `.brain/brain.db`

## Method (read this first)

This is a **pack-vs-dump** proxy:

- **Dump arm:** concatenate scenario `target_files` into the prompt.
- **Pack arm:** inject `compile_context_pack` text (≤1500-token product cap on pack body).

It does **not** drive Google Antigravity IDE, does **not** count `grep_search` / `view_file` hops, and does **not** measure multi-turn agent trajectories. Full-tool A/B (Cursor SDK / live AGY) is deferred.

Same metric class as `brainkm bench run compare` and the Antigravity live pack-vs-dump report.

## Headline (context size)

- **Dump → pack size reduction:** **95.7%** (18,642 → 794 tokens, ~23.5×).
- **Keyword hit rate:** not scored (``tokens-only`` mode or no finished LLM runs).
- **Latency:** omitted as a savings claim — only compare wall times when **both** arms finish; failed dump arms return quickly with 0 completion tokens.

## Scenario matrix

| Scenario | Arm | Context body tok | Prompt tok | Completion | Total | Status | Keyword hit | Wall |
|----------|-----|------------------|------------|------------|-------|--------|-------------|------|
| `agy_arch_pivot` | dump (files) | 11,276 | 11,276 | — | **11,276** | `tokens_only` | — | — |
| `agy_arch_pivot` | **pack (brainkm)** | 844 | 844 | — | **844** | `tokens_only` | — | — |
| `agy_ast_refactor` | dump (files) | 29,638 | 29,638 | — | **29,638** | `tokens_only` | — | — |
| `agy_ast_refactor` | **pack (brainkm)** | 757 | 757 | — | **757** | `tokens_only` | — | — |
| `agy_git_join` | dump (files) | 15,013 | 15,013 | — | **15,013** | `tokens_only` | — | — |
| `agy_git_join` | **pack (brainkm)** | 780 | 780 | — | **780** | `tokens_only` | — | — |

## Previews (LLM mode only)

_No LLM responses in `tokens-only` mode._

---

## Reproduce

```bash
# Local economics only (no API key)
PYTHONPATH=brainkm .venv/bin/python brainkm/scripts/antigravity_trajectory_bench.py \
  --mode tokens-only

# Optional live LLM (Groq or Gemini)
PYTHONPATH=brainkm .venv/bin/python brainkm/scripts/antigravity_trajectory_bench.py \
  --mode llm --driver auto
```
