# LongMemEval-S retrieval footnote (full 500)

- **brainkm version:** 0.5.0
- **date:** 2026-07-19
- **dataset:** `longmemeval_s_cleaned.json` (HuggingFace `xiaowu0162/longmemeval-cleaned`)
- **protocol:** retrieval-only `recall_any@K` + **recall@budget** (gold session in ≤1500-token pack)
- **index:** dual-grain default — whole-session **blobs for FTS** (`mode=fts-blob`)
- **sample:** **full 500 questions** (`--stratify 0 --seed 42`)
- **command:** `brainkm bench run longmemeval --stratify 0 --seed 42`
- **raw log:** [2026-07-19-longmemeval-s-full-blob.log](2026-07-19-longmemeval-s-full-blob.log)

## Headline (on our terms)

| Metric | brainkm (fts-blob) | Notes |
|--------|-------------------|-------|
| **recall@budget** | **0.892** | Gold session present in ≤1500-token pack |
| Mean pack tokens | **373** / 1500 | Hard budget |
| Pack noise rate | **0.724** | Fraction of pack ids that are non-gold |

## Shared-protocol footnote (vs agentmemory)

| Metric | brainkm (FTS blob) | agentmemory (published) |
|--------|-------------------|-------------------------|
| **R@5** | **0.934** | **0.952** (BM25+MiniLM, full 500) |
| **R@10** | **0.962** | 0.986 |
| **P@5** | **0.317** | — |
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

## Indexing history

| Run | Mode | R@5 | recall@budget |
|-----|------|-----|---------------|
| 2026-07-18 | FTS session blobs | **0.934** | — |
| 2026-07-19 (midday) | FTS chunked | 0.908 | — |
| **2026-07-19 (dual-grain)** | **FTS blob (default)** | **0.934** | **0.892** |

Dual-grain restores blob FTS for lexical ranking and keeps chunk embeddings available
for `--semantic` hybrid. Stratified hybrid (`hybrid-dual-grain`, n=48) did **not** beat
FTS on this sample (R@5 0.729) — vector reordering can demote lexical hits; full-500
`--semantic` deferred. Legacy all-chunk index: `--chunked`.

## Caveats

- Retrieval-only — **not** official LongMemEval QA + LLM judge.
- recall@budget is the product-shaped headline; R@K remains the shared-protocol footnote.
- Primary coding-agent diagnostic remains **CMA** (recall@budget + hard-slice lift).

## Reproduce

```bash
export LONGMEMEVAL_PATH=~/.cache/brainkm/longmemeval_s_cleaned.json
brainkm bench run longmemeval --stratify 0 --seed 42
```
