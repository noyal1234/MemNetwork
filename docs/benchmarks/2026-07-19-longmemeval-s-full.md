# LongMemEval-S retrieval footnote (full 500)

- **brainkm version:** 0.5.0
- **commit:** b305cfe
- **date:** 2026-07-19
- **dataset:** `longmemeval_s_cleaned.json` (HuggingFace `xiaowu0162/longmemeval-cleaned`)
- **protocol:** retrieval-only `recall_any@K` on **chunked** session haystacks
  (~480 chars, 64 overlap; ranks aggregated to session ids)
- **embedder:** FTS default (`mode=fts-chunked`; semantic off)
- **sample:** **full 500 questions** (`--stratify 0 --seed 42`)
- **command:** `brainkm bench run longmemeval --stratify 0 --seed 42`
- **raw log:** [2026-07-19-longmemeval-s-full.log](2026-07-19-longmemeval-s-full.log)

## Headline

| Metric | brainkm (FTS chunked) | agentmemory (published) |
|--------|----------------------|-------------------------|
| **R@5** | **0.908** | **0.952** (BM25+MiniLM, full 500) |
| **R@10** | **0.926** | 0.986 |
| **P@5** | **0.402** | — |
| **MRR** | **0.834** | 0.882 |

### By question type (R@5)

| Type | R@5 | n |
|------|-----|---|
| knowledge-update | 0.987 | 78 |
| multi-session | 0.970 | 133 |
| temporal-reasoning | 0.925 | 133 |
| single-session-assistant | 0.875 | 56 |
| single-session-user | 0.843 | 70 |
| single-session-preference | 0.567 | 30 |

## vs prior published footnote

| Run | Mode | R@5 | R@10 | MRR |
|-----|------|-----|------|-----|
| 2026-07-18 | FTS session blobs (pre-chunk) | **0.934** | 0.962 | 0.861 |
| **2026-07-19** | FTS chunked (current default) | **0.908** | 0.926 | 0.834 |

Chunking recovered MiniLM hybrid from ~0.37 R@5 on stratified samples (see
[2026-07-19-longmemeval-chunked.md](2026-07-19-longmemeval-chunked.md)) but lowers
full-500 FTS vs whole-session blobs — mainly `single-session-preference`
(0.800 → 0.567) and `single-session-assistant` (1.000 → 0.875).

## Caveats

- Retrieval-only — **not** official LongMemEval QA + LLM judge.
- Stratified hybrid (`fts_primary`) matches the FTS floor on n=30; full-500
  `--semantic` not re-run here (expected ≈ FTS under `fts_primary`).
- Primary public claim remains **CMA v3**.

## Reproduce

```bash
export LONGMEMEVAL_PATH=~/.cache/brainkm/longmemeval_s_cleaned.json
brainkm bench run longmemeval --stratify 0 --seed 42
```
