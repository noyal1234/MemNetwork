# Benchmarks

Product-grade evaluation for brainkm retrieval quality, task success, and latency.
Regenerate on release (local — CI deferred while the repo is private):

```bash
brainkm bench run eval --project-dir .
# or: bash brainkm/scripts/run_eval.sh
```

**Public shared-metric footnote (vs agentmemory):** LongMemEval-S retrieval `recall_any@K`
on the same cleaned corpus. **Diagnostic suite (coding shape):** Common Memory Axes (CMA).
Head-to-head notes: [benchmarks/COMPARISON.md](benchmarks/COMPARISON.md).

```bash
bash brainkm/scripts/run_cma.sh
# or: brainkm bench run cma --write-scorecard docs/benchmarks/YYYY-MM-DD-cma.md
```

Individual suites:

```bash
brainkm bench run retrieval
brainkm bench run task
brainkm bench run latency --profile both
brainkm bench run compare   # token proxy only (generous baseline)
brainkm bench run cma       # Common Memory Axes (abilities + tokens + latency)
brainkm bench run scorecard # decision vs structure differentiator
brainkm bench run longmemeval  # LongMemEval-S retrieval footnote (+ --semantic --adapters)
brainkm bench run staleness # supersede / stale-injection
brainkm bench run scale     # R@5 + latency at growing corpus sizes
brainkm bench run cost      # injected tokens/session + $/yr model
```

Optional LLM judge (Ollama): `brainkm bench run task --judge`

## Common Memory Axes (CMA) — primary public scorecard

Chat-memory vendors (Mem0, Zep, agentmemory) often cite **LoCoMo**, **LongMemEval**, or **BEAM**. Those corpora are multi-session **chat** haystacks. brainkm is a **coding-agent project brain** (neurons + code graph + ≤1500-token packs).

CMA reuses LongMemEval’s *ability language* on a coding-agent fixture so numbers are comparable in spirit without pretending to be a chat-assistant leaderboard score:

| Ability | What we measure |
|---------|-----------------|
| `extraction` | Gold neuron in top-5 |
| `knowledge_update` | After `supersedes`, top hit is the **new** fact |
| `abstention` | Off-topic queries abstain / empty |
| `multi_hop` | `traverse` / graph-aware recall |
| `multi_session` | Facts evolving across seeded sessions |
| `procedure` | Procedure neuron ranked for how-to queries |

**Always reported as a triple:** ability micro-average + mean pack tokens (≤1500) + recall/pack p95 latency.

**Baselines (same gold):** BM25/FTS-only and naive title/content token scan.

Latest published artifact: [docs/benchmarks/2026-07-19-cma-v3.md](benchmarks/2026-07-19-cma-v3.md) (brainkm **0.5.0**, CMA **v3**, semantic off):

| Metric | Result |
|--------|--------|
| Ability micro-avg | **100%** (hard subset **100%**, n=32) |
| Mean pack tokens | **~322** / 1500 |
| Recall / pack p95 | **~13 / 18 ms** |
| Baselines (full) | brain **1.00** vs BM25 **0.88** / title-scan **0.83** |
| Hard-slice lift | brain **1.00** vs BM25 **0.55** (**+0.45**, n=11 paraphrase/bridge) |
| Decision+structure scorecard | **8/8** |
| Theme-leak (gated) | **2/2** (off-domain abstain) |

Prior: [2026-07-18 cma-v3](benchmarks/2026-07-18-cma-v3.md), [cma-v2](benchmarks/2026-07-18-cma-v2.md), [cma-v1](benchmarks/2026-07-18-cma.md).

### LongMemEval-S retrieval footnote (shared metric vs agentmemory)

**Full 500** — [docs/benchmarks/2026-07-19-longmemeval-s-full.md](benchmarks/2026-07-19-longmemeval-s-full.md) (FTS **chunked**):

| Metric | brainkm (FTS chunked) | agentmemory (published) |
|--------|----------------------|-------------------------|
| **R@5** | **0.908** | **0.952** (BM25+MiniLM) |
| **R@10** | **0.926** | 0.986 |
| **P@5** | **0.402** | — |
| **MRR** | **0.834** | 0.882 |

Prior blob-FTS full-500 (pre-chunk, 2026-07-18): R@5 **0.934** — see that artifact for history.
Chunking recovered MiniLM hybrid on stratified samples but trades some FTS R@5 on full-500
(mainly preference / assistant single-session). See [COMPARISON.md](benchmarks/COMPARISON.md).

Also: [stratified chunked + adapters](benchmarks/2026-07-19-longmemeval-chunked.md),
[2026-07-18 full blob FTS](benchmarks/2026-07-18-longmemeval-s-full.md).

### Market-standard + unique suites

| Suite | What |
|-------|------|
| `retrieval` | Recall@k + **Precision@k** + MRR/nDCG + abstain + theme-leak |
| `staleness` | Superseded fact must not outrank / leak into packs |
| `scale` | R@5 + p95 latency at 1k / 10k (/ 50k) synthetic neurons |
| `cost` | Injected tokens/session + distill tokens + $/yr model |

### What we refuse to claim

- CMA is **not** “LongMemEval-S R@5”. Different protocol and corpus.
- Official LongMemEval **QA + LLM judge** is out of scope for v1.
- LoCoMo / BEAM are deferred (wrong shape / scale).

### Optional LongMemEval-S retrieval footnote

For an apples-to-apples *retrieval* footnote against agentmemory’s protocol:

```bash
# Download cleaned JSON (~264MB), then:
export LONGMEMEVAL_PATH=~/.cache/brainkm/longmemeval_s_cleaned.json
brainkm bench run longmemeval --stratify 10 --seed 42
brainkm bench run longmemeval --stratify 10 --semantic --adapters
brainkm bench run longmemeval --stratify 0                 # full 500 (slow)
```

Without a dataset the suite **skips cleanly** (PASS with instructions). Requires `pip install -e "./brainkm[semantic]"` for `--semantic`.

## Headline results (MemNetwork project brain, brainkm 0.3.2)

> Measured on **0.3.2**; retrieval/latency methodology unchanged in **0.4.x**. Re-run `bench run eval` after major retrieval changes. Prefer **CMA** for public agentic-memory comparison.

Hardware / corpus: macOS (darwin), hashing embedder (semantic off), **populated** `.brain/brain.db` (~1483 code nodes + project neurons), measured **2026-07-16**.

### Product-grade (`bench run eval`)

| Suite | Metric | Result | Notes |
|-------|--------|--------|-------|
| **Retrieval** | Recall@1 / Recall@5 | **0.80 / 0.91** (54 ranking queries) | Held-out gold corpus (`retrieval_v1`, 64 queries) |
| **Retrieval** | MRR / nDCG@5 | **0.94 / 0.91** | Ephemeral gold corpus; floors in fixture |
| **Retrieval** | Theme-leak accuracy | **100%** (5/5) | In-corpus noise queries: theme neurons must not appear in top-5 |
| **Retrieval** | Abstain accuracy | **100%** (5/5) | True off-topic queries with abstention enabled |
| **Task** | Gold-fact coverage | **with 100% / without 85%** | 23 MemNetwork tasks; selective-read baseline (not full files) |
| **Task** | Pass rate | **23/23 (100%)** | Hard gate: all `answer_facts` in pack + pack ≤1500 |
| **Latency smoke** | recall / pack p95 | **0.9 / 1.1 ms** | Ephemeral tiny brain; targets ≤150 / ≤250 ms |
| **Latency loaded** | recall / pack p95 | **648 / 758 ms** | Live brain; targets ≤1200 / ≤1500 ms |
| **Eval aggregate** | All cases | **84/84 (100%)** | Includes regression canaries below |

### Token proxy (`compare` — generous baseline)

Naive multi-file dump vs `context_pack`. **Not** the task-success metric; use for savings demos only.

| Scenario | Without | With | Savings |
|----------|---------|------|---------|
| token_budget | 9987 | 607 | 16.5× |
| mcp_dispatch | 7014 | 457 | 15.3× |
| graphify_routing | 11074 | 898 | 12.3× |
| session_snapshot | 5241 | 347 | 15.1× |

Average **~94% reduction (~15.7×)** across 4 scenarios.

### Regression canaries (not headline claims)

| Suite | Result | DB |
|-------|--------|-----|
| Abstention | 10/10 | Ephemeral + calibrate |
| DMR-lite | 5/5 | Ephemeral |
| LongMemEval-lite | 10/10 | Ephemeral |
| Budget | 8/8 | Ephemeral |
| Compaction | 3/3 | Ephemeral |
| Token (fixture) | 10/10 | Ephemeral |

## What each suite measures

| Suite | Brain | Standard metric |
|-------|-------|-----------------|
| `cma` | Ephemeral coding-agent corpus | Ability micro-avg + mean pack tokens + latency p95 |
| `scorecard` | Ephemeral | Decision recall + structure traverse |
| `longmemeval` | Ephemeral per question | Optional LongMemEval-S recall_any@K (skips without dataset) |
| `retrieval` | Ephemeral gold corpus | Recall@k, MRR, nDCG@5, theme-leak + abstain accuracy |
| `task` | Live project brain | `answer_facts` answerability + gold coverage vs selective-read |
| `latency` | Smoke ephemeral + loaded live | Cold/warm p50/p95, mean±stdev |
| `compare` | Live | Token savings vs naive file dump (proxy) |
| `eval` | Mixed | All of the above product suites + canaries |

**Fixture vs live:** `retrieval` uses isolated gold neurons (ranking science). `task` and `latency --profile loaded` use the real project brain. Canaries are tiny regression fixtures.

## Task success (with brain vs without)

**Without brain** = selective token-capped excerpts from neighborhood files (Cursor-like partial reads, not whole-file dumps).

**With brain** = bounded `context_pack` from `.brain/brain.db`.

Pass requires **all** `answer_facts` phrases in the with-brain pack (not merely substring coverage). The selective-read baseline is the without arm.

```bash
brainkm bench run task --project-dir .
brainkm bench run task --project-dir . --judge   # optional Ollama rubric
```

One-off probe:

```bash
brainkm bench probe "how does token budget greedy truncation work" --project-dir . \
  --baseline brainkm/brainkm/services/budget.py \
  --baseline brainkm/brainkm/services/context_pack.py
```

## Latency profiles

```bash
brainkm bench run latency --profile smoke   # tight SLOs, empty-ish brain
brainkm bench run latency --profile loaded  # corpus-scaled SLOs
brainkm bench run latency --profile both    # default for eval
```

Loaded targets are calibrated for populated brains (~1k+ code nodes). Smoke targets remain the fast-path SLO.

## Semantic (opt-in)

ONNX MiniLM + CE rerank: `pip install -e "./brainkm[semantic]"` + `brainkm semantic doctor`. Not part of default eval gate.

## Noise control and policy surfacing (0.3.2+)

Product fixes behind the split retrieval metrics and redaction task pass:

- **FTS overlap filter** — multi-token queries drop single-token collision hits (e.g. `learning`, `score`, `gate`) after OR-FTS retrieval.
- **Abstention BM25 floor** — `RecallConfig.min_bm25_strength` (default 3.0) abstains when best BM25 is weak even if percentile would pass.
- **Pack policy surfacing** — code recall hits seed graph neighborhood; `summary_first` preserves policy markers (`remember_neuron`, `redact`, etc.) for rule/decision neurons.

## Before / after product-grade eval

| Dial | Before | After (0.3.2+) |
|------|--------|----------------|
| Retrieval quality | Top-1 pass/fail on 5–10 fixtures | Recall@k / MRR / nDCG on 64-query gold set |
| Noise control | Conflated “abstain” (~70% leak) | Split theme-leak vs true abstain metrics |
| Task success | Token savings only | `answer_facts` answerability vs selective-read |
| Latency | Single profile, empty-brain targets | Smoke + loaded SLOs, cold/warm variance |
| Adoption story | `compare` file-dump proxy | `task` primary; `compare` labeled proxy |
| Judge | None | Optional Ollama `--judge` (soft) |

Exact numbers are environment-dependent; refresh from `bench run eval` / `bench run cma` on each release. Product eval CI remains deferred while the repo is private; [`.github/workflows/bench.yml`](../.github/workflows/bench.yml) is ready for public CMA gates (LongMemEval-S is `workflow_dispatch` only).
