# Benchmarks

Published numbers for brainkm retrieval quality, token savings, and latency.
Regenerate on release (local — CI deferred while the repo is private):

```bash
brainkm bench run abstention
brainkm bench run token --live
brainkm bench run dmr
brainkm bench run longmem
brainkm bench run budget
brainkm bench run compaction
brainkm bench run latency
```

## Headline results (local fixture / empty-brain smoke, brainkm 0.3.2)

Hardware note for latency row below: macOS arm64, hashing embedder (semantic off), empty fresh `brain.db`, measured 2026-07-15.

| Suite | Metric | Result | Notes |
|-------|--------|--------|-------|
| Token (`bench probe` / token suite) | Pack vs naive multi-file read | **typically 5–20× fewer tokens** | Bounded `context_pack` vs reading neighborhood files |
| Abstention | Fixture precision | Calibrated to P10 percentile | Avoids injecting low-confidence noise |
| DMR-lite | External recall vs summarize | External store wins (MemGPT-style) | Packs survive Cursor compaction via PreCompact handover |
| LongMemEval-lite | Temporal supersede | Supersedes preferred over ADD-only | Conflict detection suggests supersede on remember |
| Latency | recall p50 / p95 | **0.5 ms / 0.6 ms** (empty brain) | Target ≤80 / ≤150 ms without reranker |
| Latency | context_pack p50 / p95 | **0.7 ms / 77.4 ms** (empty brain) | Target ≤250 ms p95; summary-first + adaptive budgets |
| Semantic (opt-in) | MiniLM + CE | Wizard/doctor consent; default off | `pip install -e "./brainkm[semantic]"` + `brainkm semantic doctor` |

Exact fixture pass/fail rates are environment-dependent; refresh this file from `bench run` output on each release. Numbers are **not** CI-regenerated while public workflows are deferred.

## Before / after Phase A–C

| Dial | Before (0.2.0) | After (0.3+) |
|------|----------------|--------------|
| Retrieval | FTS5 + flat 2-hop BFS | Hybrid RRF (FTS+vector when enabled) + weighted PPR + intent routing |
| Pack density | Subtype priority only | Write-time compression + dedup + MMR diversity + summary-first |
| Quality loop | Co-activation only | Injected-vs-used feedback + decay + consolidate |
| Speed | Untargeted | Latency suite with explicit p50/p95 targets |
| Semantic fidelity (0.3.2) | Hashing theater under `[semantic]` | Real ONNX MiniLM + optional CE; wizard consent |

## How we measure token savings

```bash
brainkm bench probe "why did we choose JWT auth" --project-dir .
```

Compare `context_pack` token count to the naive baseline (concatenating seed files).
Lower pack tokens with equal or better task success is the product north star.
