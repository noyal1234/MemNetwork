# LongMemEval-S retrieval footnote

- **brainkm version:** 0.4.1
- **date:** 2026-07-18
- **machine:** macOS-26.5.2-x86_64-i386-64bit
- **dataset:** `longmemeval_s_cleaned.json` (HuggingFace `xiaowu0162/longmemeval-cleaned`)
- **protocol:** retrieval-only `recall_any@K` on session haystacks (FTS+graph default, semantic off)
- **sample:** stratified 10 questions × 6 types = 60 questions (`--stratify 10`)
- **command:** `brainkm bench run longmemeval --stratify 10`

## Headline

| Metric | Result |
|--------|--------|
| **R@5** | **0.917** (55/60) |
| **R@10** | **0.950** |
| **MRR** | **0.847** |

### By question type (R@5)

| Type | R@5 | n |
|------|-----|---|
| knowledge-update | 1.000 | 10 |
| multi-session | 1.000 | 10 |
| single-session-assistant | 1.000 | 10 |
| single-session-user | 0.900 | 10 |
| temporal-reasoning | 0.900 | 10 |
| single-session-preference | 0.700 | 10 |

## Caveats

- This is **not** official LongMemEval QA accuracy (no LLM reader / judge).
- agentmemory publishes ~95.2% R@5 on the **full** 500-Q set with BM25+MiniLM hybrid.
- Our footnote uses **FTS default** (semantic off) on a **stratified 60-Q** sample.
- Primary public claim remains **CMA** (coding-agent corpus). See `2026-07-18-cma-v2.md`.

## Reproduce

```bash
export LONGMEMEVAL_PATH=~/.cache/brainkm/longmemeval_s_cleaned.json
brainkm bench run longmemeval --stratify 10
# full set: --stratify 0
```
