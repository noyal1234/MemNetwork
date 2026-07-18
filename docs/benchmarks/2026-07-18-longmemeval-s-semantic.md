# LongMemEval-S retrieval footnote — FTS vs MiniLM hybrid

- **brainkm version:** 0.4.1
- **date:** 2026-07-18
- **dataset:** `longmemeval_s_cleaned.json` (HuggingFace `xiaowu0162/longmemeval-cleaned`)
- **protocol:** retrieval-only `recall_any@K` on session haystacks (≤4k chars/session)
- **sample:** stratified **60** (10 per question type)
- **commands:**
  - FTS: `brainkm bench run longmemeval --stratify 10`
  - MiniLM: `brainkm bench run longmemeval --stratify 10 --semantic` (`[semantic]` extra + ONNX MiniLM)

## Side-by-side

| Mode | R@5 | R@10 | MRR |
|------|-----|------|-----|
| **FTS** (published default) | **0.917** | **0.950** | **0.847** |
| **MiniLM hybrid** (`--semantic`) | 0.367 | 0.500 | 0.250 |

### By question type (R@5)

| Type | FTS | MiniLM |
|------|-----|--------|
| knowledge-update | 1.000 | 0.400 |
| multi-session | 1.000 | 0.400 |
| single-session-assistant | 1.000 | 0.200 |
| single-session-preference | 0.700 | 0.500 |
| single-session-user | 0.900 | 0.400 |
| temporal-reasoning | 0.900 | 0.300 |

## Takeaway

On this protocol, embedding long truncated session blobs and RRF-fusing with FTS **hurts** recall vs FTS alone. The **full-500 published footnote stays FTS** ([longmemeval-s-full.md](2026-07-18-longmemeval-s-full.md)). MiniLM remains valuable for short neuron paraphrase in product configs; it is not a free lift on LongMemEval-S session haystacks as wired today.

Primary public claim remains **CMA v3** ([cma-v3.md](2026-07-18-cma-v3.md)).
