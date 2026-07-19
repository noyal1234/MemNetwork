# brainkm vs agentmemory — comparison notes

Apples-to-apples where possible. Vendor figures we did not reproduce are labeled.

## Shared protocol: LongMemEval-S retrieval (not official QA)

Both projects measure **`recall_any@K`** on the cleaned LongMemEval-S haystacks
([xiaowu0162/longmemeval-cleaned](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned)):
index sessions for one question, retrieve with the question text, check whether any
gold session id appears in the top-K. **No LLM judge** — this is retrieval only.

| System | Mode | R@5 | R@10 | MRR | Notes |
|--------|------|-----|------|-----|-------|
| **agentmemory** (published) | BM25 + MiniLM | **0.952** | 0.986 | 0.882 | Their measured result |
| agentmemory (published) | BM25-only | 0.862 | 0.946 | 0.715 | Their fallback |
| **brainkm** (2026-07-19) | FTS chunked | **0.908** | 0.926 | 0.834 | Full 500; [artifact](2026-07-19-longmemeval-s-full.md) |
| brainkm (2026-07-18) | FTS session blobs | 0.934 | 0.962 | 0.861 | Pre-chunk; historical |
| **brainkm** (chunked + fts_primary) | FTS candidates re-ranked by MiniLM | ~FTS floor | | | Stratified n=30: R@5 **0.867** = FTS; see `--semantic` |

Caveats (same honesty bar agentmemory uses in their COMPARISON.md):

- Mem0 / Letta LoCoMo numbers are a **different dataset** — not shown as head-to-head here.
- Official LongMemEval **QA accuracy** (retrieve + generate + GPT judge) is out of scope for brainkm v1.
- brainkm MiniLM hybrid previously collapsed to ~0.37 R@5 when embedding whole 4k-char sessions into a 128-token encoder; indexing now **chunks** sessions before embed/FTS and aggregates ranks back to session ids.

Reproduce:

```bash
export LONGMEMEVAL_PATH=~/.cache/brainkm/longmemeval_s_cleaned.json
brainkm bench run longmemeval --stratify 0            # full FTS
brainkm bench run longmemeval --stratify 10 --semantic --adapters
```

## What brainkm measures that chat-memory vendors usually do not

| Axis | Suite | Why it matters for coding agents |
|------|-------|-----------------------------------|
| Abstention / theme-leak | `retrieval`, `cma` | Keyword collisions must not inject junk |
| Hard token cap (≤1500) | `cma`, `cost`, `task` | Packs stay injectable |
| Compaction survival | `compaction` canary | Truth survives host summarize |
| Code-graph structure | `scorecard`, `cma` multi_hop | Blast-radius / traverse quality |
| Supersede / staleness | `staleness` | Updated facts outrank archived ones |
| Scale curve | `scale` | R@5 + p95 latency at 1k/10k/50k |
| Cost model | `cost` | Injected tokens/session + $/yr estimate |

## Coding-agent diagnostic (CMA) — not a LongMemEval claim

CMA is a **self-authored coding-agent corpus** (neurons + edges + supersedes). Use it to
diagnose abilities; do **not** present CMA micro-avg as “LongMemEval R@5”.

Latest: [2026-07-19-cma-v3.md](2026-07-19-cma-v3.md) — ability micro **100%**, hard-slice
brain **1.00** vs BM25 **0.55**, mean pack **~322**/1500, theme_leak **2/2**.

## Product shape (why scores diverge)

| | brainkm | agentmemory |
|--|---------|-------------|
| Primary store | Project SQLite brain + Graphify AST | Local memory engine + MCP |
| Pack budget | Hard ≤1500 tokens | ~1.9k tokens/session (their model) |
| Code graph | First-class `traverse` | Not the same product axis |
| Hosts | Cursor / Claude / Antigravity hooks | Broad MCP client list |

## Deferred

- Full LoCoMo / BEAM runs (wrong shape for a project brain).
- Official LongMemEval QA + LLM judge.
- Running agentmemory’s TypeScript harness against brainkm (nice-to-have).
