# LongMemEval-S retrieval footnote (full 500)

- **brainkm version:** 0.4.1
- **date:** 2026-07-18
- **dataset:** `longmemeval_s_cleaned.json` (HuggingFace `xiaowu0162/longmemeval-cleaned`)
- **protocol:** retrieval-only `recall_any@K` on session haystacks
- **embedder:** FTS default (semantic off / hashing fallback)
- **sample:** **full 500 questions** (`--stratify 0`)
- **command:** `brainkm bench run longmemeval --stratify 0`

## Headline

| Metric | brainkm (FTS) | agentmemory (published) |
|--------|---------------|-------------------------|
| **R@5** | **0.934** | **0.952** (BM25+MiniLM, full 500) |
| **R@10** | **0.962** | 0.986 |
| **MRR** | **0.861** | 0.882 |

### By question type (R@5)

| Type | R@5 | n |
|------|-----|---|
| knowledge-update | 1.000 | 78 |
| single-session-assistant | 1.000 | 56 |
| multi-session | 0.955 | 133 |
| temporal-reasoning | 0.925 | 133 |
| single-session-user | 0.843 | 70 |
| single-session-preference | 0.800 | 30 |

## Caveats

- Retrieval-only — **not** official LongMemEval QA + LLM judge.
- MiniLM hybrid side-by-side (stratified): [longmemeval-s-semantic.md](2026-07-18-longmemeval-s-semantic.md) — FTS wins; this full-500 run stays FTS-default.
- Primary public claim remains **CMA v3**.

## Reproduce

```bash
export LONGMEMEVAL_PATH=~/.cache/brainkm/longmemeval_s_cleaned.json
brainkm bench run longmemeval --stratify 0
```
