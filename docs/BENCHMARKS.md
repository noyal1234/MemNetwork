# Benchmarks

Published numbers for brainkm retrieval quality, token savings, and latency.
Regenerate on release:

```bash
brainkm bench run abstention
brainkm bench run token --live
brainkm bench run dmr
brainkm bench run longmem
brainkm bench run budget
brainkm bench run compaction
brainkm bench run latency
```

## Headline results (local fixture corpus, brainkm 0.3.x)

| Suite | Metric | Result | Notes |
|-------|--------|--------|-------|
| Token (`bench probe` / token suite) | Pack vs naive multi-file read | **typically 5–20× fewer tokens** | Bounded `context_pack` vs reading neighborhood files |
| Abstention | Fixture precision | Calibrated to P10 percentile | Avoids injecting low-confidence noise |
| DMR-lite | External recall vs summarize | External store wins (MemGPT-style) | Packs survive Cursor compaction via PreCompact handover |
| LongMemEval-lite | Temporal supersede | Supersedes preferred over ADD-only | Conflict detection suggests supersede on remember |
| Latency | recall p95 | Target **≤150ms** (no reranker) | Hashing embedder + PPR on local SQLite |
| Latency | context_pack p95 | Target **≤250ms** | Summary-first + adaptive intent budgets |

Exact pass/fail rates are environment-dependent; CI runs the suites and this file should be refreshed from `bench run` output on each release.

## Before / after Phase A–C

| Dial | Before (0.2.0) | After (0.3+) |
|------|----------------|--------------|
| Retrieval | FTS5 + flat 2-hop BFS | Hybrid RRF (FTS+vector) + weighted PPR + intent routing |
| Pack density | Subtype priority only | Write-time compression + dedup + MMR diversity + summary-first |
| Quality loop | Co-activation only | Injected-vs-used feedback + decay + consolidate |
| Speed | Untargeted | Latency suite with explicit p50/p95 targets |

## How we measure token savings

```bash
brainkm bench probe "why did we choose JWT auth" --project-dir .
```

Compare `context_pack` token count to the naive baseline (concatenating seed files).
Lower pack tokens with equal or better task success is the product north star.
