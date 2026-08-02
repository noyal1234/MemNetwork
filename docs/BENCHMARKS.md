# Benchmarks

Product-grade evaluation for brainkm retrieval quality, task success, and latency.
Regenerate on release (local — CI deferred while the repo is private):

```bash
brainkm bench run eval --project-dir .
# or: bash brainkm/scripts/run_eval.sh
```

**Headline metric:** **recall@budget** — gold fact present in the ≤1500-token pack
(+ pack noise). Framed on brainkm’s product contract, not chat-haystack top-K.
**Shared-protocol footnote (vs agentmemory):** LongMemEval-S `recall_any@K`.
**Regression gate (coding shape):** Common Memory Axes (CMA) ability micro-avg.
**Resource footprint:** idle / load RSS+CPU for `brainkm serve` —
[2026-07-21-footprint](benchmarks/2026-07-21-footprint.md).
Head-to-head notes: [benchmarks/COMPARISON.md](benchmarks/COMPARISON.md).

```bash
bash brainkm/scripts/run_cma.sh
# or: brainkm bench run cma --write-scorecard docs/benchmarks/YYYY-MM-DD-cma.md
```

### Runtime footprint (CPU / RAM)

Not a retrieval bench — grounds the “lightweight local runtime” README claim:

```bash
python brainkm/scripts/footprint_harness.py \
  --out docs/benchmarks/YYYY-MM-DD-footprint.md
```

Latest: [2026-07-21-footprint.md](benchmarks/2026-07-21-footprint.md) — idle **~55–70 MB** / **≪1% CPU**; MCP tool load peak **~110 MB**.

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

### End-task A/B (agent with brainkm vs without)

Uniform protocol **`endtask_protocol/1.1`** — shared fixture `endtask_v1`, Core/Full
tiers, MCP integrity via `session_activity`, nullable host tokens, and shared
with-arm MCP routing (`WITH_ARM_MCP_PREFIX`).

**Publish set:** **`endtask_h2h/2`** (2026-07-30, brainkm **0.9.0**) — Cursor +
Antigravity Core both measured under the same schedule. Prior cards remain under
[History](#end-task-history-preserved).

| Tier | Schedule | When to publish |
|------|----------|-----------------|
| **Core** | 6 pinned tasks × 2 × 3 = **36** | Required before claiming a host “measured” |
| **Full** | 20 tasks × 2 × 3 = **120** | Cursor-class / public Full parity (optional stretch) |

```bash
pip install -e "./brainkm[endtask]"   # cursor-sdk
export CURSOR_API_KEY=cursor_...

# Cursor Core (protocol scorecard):
python brainkm/scripts/endtask_harness.py --backend cursor --tier core --repeats 3 \
  --protocol-scorecard --require-mcp

# Antigravity Core (Google OAuth / plan quota) — prefer a flash-low model if quota is tight:
export PATH="$HOME/.local/bin:$PATH"
python brainkm/scripts/antigravity_endtask_harness.py \
  --allow-skip-permissions --home-mcp-swap --require-mcp \
  --tier core --repeats 3 --model gemini-3.6-flash-low
```

**Groq** remains knowledge-only pack A/B (`--backend groq`). Claude: pending.
**Codex** harness is ready (ChatGPT login; default cheap model):

```bash
python brainkm/scripts/codex_endtask_harness.py \
  --allow-skip-permissions --require-mcp \
  --tier core --repeats 3 \
  --model gpt-5.6-luna --reasoning-effort low
```

#### Current artifacts (`endtask_h2h/2`)

| Host | Tier | Protocol | Card |
|------|------|----------|------|
| **Cursor** | **Core** | `endtask_protocol/1.1` | [2026-07-30-endtask-cursor-core](benchmarks/2026-07-30-endtask-cursor-core.md) |
| **Antigravity** | **Core** | `endtask_protocol/1` (prefix already applied; Core-compatible) | [2026-07-22-endtask-antigravity-core](benchmarks/2026-07-22-endtask-antigravity-core.md) |

> **AGY 0.9.0 remasure not published:** multi-model / flash-low runs hit quota and
> produced only PARTIAL mcp_ok — do not replace the Jul 22 H2H card until a clean
> single-model Core remasure finishes.

#### Cross-host Core (`endtask_h2h/2`)

| Host | Pass with / without | mcp_ok | Mean MCP_db (with) | Mean prompt tokens |
|------|---------------------|--------|--------------------|--------------------|
| **Cursor** | **18/18** / 17/18 | **18/18** | **1.4** | **−30%** (71 115 vs 102 091) |
| **Antigravity** | **18/18** / 12/18 | **18/18** | **1.7** | N/A (print-mode) |
| Claude / Codex | pending | — | — | — |

Compare pass / tools / mcp across hosts; **% token reduction only** where
`tokens_supported=true` (Cursor today).

**Pack-vs-dump (public pack claim):** `compare`, Antigravity live, and
`brainkm/scripts/antigravity_trajectory_bench.py` (Antigravity-**themed** scenarios;
`--mode tokens-only` by default — **not** an IDE tool-loop bench).

#### End-task history (preserved)

| When | Label | What it is | Artifact |
|------|-------|------------|----------|
| 2026-07-21 | Cursor Full (pre-protocol) | 120 runs, content+tokens only; MCP injected but **not** gated | [2026-07-21-endtask-cursor](benchmarks/2026-07-21-endtask-cursor.md) (−5% tokens, 60/60) |
| 2026-07-22 | AGY host-smoke | Pre-protocol AGY smoke | [2026-07-22-antigravity-endtask](benchmarks/2026-07-22-antigravity-endtask.md) |
| 2026-07-30 | Cursor Core pre-routing | Protocol Core **before** WITH_ARM_MCP_PREFIX — mcp_ok **9/18** | [2026-07-30-endtask-cursor-core-pre-mcp-routing](benchmarks/2026-07-30-endtask-cursor-core-pre-mcp-routing.md) |
| 2026-07-22 | AGY Core (current AGY) | First protocol Core publish (brainkm **0.8.1**, 6 MCP tools) | [2026-07-22-endtask-antigravity-core](benchmarks/2026-07-22-endtask-antigravity-core.md) |
| 2026-07-30 | Cursor Core (current Cursor) | Protocol **1.1** + routing; mcp_ok **18/18**, **−30%** tokens | [2026-07-30-endtask-cursor-core](benchmarks/2026-07-30-endtask-cursor-core.md) |

Protocol **1 → 1.1:** same Core/Full + MCP integrity; **1.1** requires shared
`WITH_ARM_MCP_PREFIX` (and Cursor `setting_sources=project`) so `--require-mcp`
measures real brainkm use, not optional Grep/Read shortcuts.
## Headline: recall@budget (≤1500-token pack)

brainkm’s contract is not “gold in top-5 of an unbounded list” — it is **gold fact
inside a hard token budget without drowning the agent in noise**.

| Corpus | recall@budget | Mean pack tokens | Pack noise | Artifact |
|--------|---------------|------------------|------------|----------|
| CMA v3 (coding-agent) | **0.810** | **175** / 1500 | 0.721 | [2026-07-31-cma](benchmarks/2026-07-31-cma.md) |
| LongMemEval-S full 500 | **0.892** | **373** / 1500 | 0.724 | [lme-full](benchmarks/2026-07-19-longmemeval-s-full.md) |

Agentmemory’s published LongMemEval protocol does not report a hard pack budget
(~1.9k tokens/session in their cost model). recall@budget is the comparison framed
on our terms; see [COMPARISON.md](benchmarks/COMPARISON.md).

## Common Memory Axes (CMA) — coding-agent diagnostic + regression gate

Chat-memory vendors (Mem0, Zep, agentmemory) often cite **LoCoMo**, **LongMemEval**, or **BEAM**. Those corpora are multi-session **chat** haystacks. brainkm is a **coding-agent project brain** (neurons + code graph + ≤1500-token packs).

CMA reuses LongMemEval’s *ability language* on a coding-agent fixture. **Quote
recall@budget + hard-slice lift** publicly; ability micro-avg is a **regression gate**
(currently saturated at 100% and no longer discriminative).

| Ability | What we measure |
|---------|-----------------|
| `extraction` | Gold neuron in top-5 |
| `knowledge_update` | After `supersedes`, top hit is the **new** fact |
| `abstention` | Off-topic queries abstain / empty |
| `multi_hop` | `traverse` / graph-aware recall |
| `multi_session` | Facts evolving across seeded sessions |
| `procedure` | Procedure neuron ranked for how-to queries |

Latest published artifact: [docs/benchmarks/2026-07-31-cma.md](benchmarks/2026-07-31-cma.md) (brainkm **0.9.0**, CMA **v3**):

| Metric | Result |
|--------|--------|
| **recall@budget** | **0.810** (floor ≥0.80, n=42) |
| Pack noise | **0.721** (report-only) |
| Mean pack tokens | **~175** / 1500 |
| Ability micro-avg (gate) | **100%** (hard subset **100%**, n=32) |
| Recall / pack p95 | **~9 / 14 ms** |
| Baselines (full) | brain **1.00** vs BM25 **0.88** / title-scan **0.83** |
| Hard-slice lift | brain **1.00** vs BM25 **0.55** (**+0.45**, n=11) |
| Decision+structure scorecard | **8/8** |
| Theme-leak (gated) | **2/2** |

Prior: [2026-07-19-cma-v3-budget](benchmarks/2026-07-19-cma-v3-budget.md) (0.5.0), [cma-v3](benchmarks/2026-07-19-cma-v3.md), [2026-07-18 cma-v3](benchmarks/2026-07-18-cma-v3.md).

### LongMemEval-S shared-protocol footnote (vs agentmemory)

**Full 500** — [docs/benchmarks/2026-07-19-longmemeval-s-full.md](benchmarks/2026-07-19-longmemeval-s-full.md) (**fts-blob** dual-grain default):

| Metric | brainkm (FTS blob) | agentmemory (published) |
|--------|-------------------|-------------------------|
| **recall@budget** | **0.892** @ 373 tok | — (no hard pack budget reported) |
| **R@5** | **0.934** | **0.952** (BM25+MiniLM) |
| **R@10** | **0.962** | 0.986 |
| **MRR** | **0.861** | 0.882 |

Dual-grain indexing (blob FTS + optional chunk vectors) restored the pre-chunk FTS floor.
Legacy all-chunk: `--chunked`. Stratified hybrid did not beat FTS — see
[dual-grain semantic note](benchmarks/2026-07-19-longmemeval-dual-grain-semantic.md).

Also: [chunked mid-day run](benchmarks/2026-07-19-longmemeval-chunked.md) (R@5 0.908, historical).

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
brainkm bench run longmemeval --stratify 10 --seed 42      # fts-blob + recall@budget
brainkm bench run longmemeval --stratify 10 --semantic     # dual-grain hybrid sanity
brainkm bench run longmemeval --stratify 0                 # full 500 (slow)
brainkm bench run longmemeval --chunked --stratify 10      # legacy all-chunk index
```

Without a dataset the suite **skips cleanly** (PASS with instructions). Requires `pip install -e "./brainkm[semantic]"` for `--semantic`.

## Headline results (MemNetwork project brain, brainkm 0.9.0)

> Measured on **0.9.0** (2026-07-31). Public agentic-memory claim remains **CMA**
> ([2026-07-31-cma](benchmarks/2026-07-31-cma.md)); product `eval` below is regression
> signal on this repo’s live brain. Historical 0.3.2 snapshot kept only in git history
> of this file.

Hardware / corpus: macOS (darwin), hashing embedder (semantic off), **populated**
`.brain/brain.db` (code graph + project neurons).

### Product-grade (`bench run eval`)

| Suite | Metric | Result | Notes |
|-------|--------|--------|-------|
| **Retrieval** | Recall@1 / Recall@5 | **0.80 / 0.91** (54 ranking queries) | Held-out gold corpus (`retrieval_v1`, 64 queries) |
| **Retrieval** | MRR / nDCG@5 | **0.94 / 0.91** | Ephemeral gold corpus; floors in fixture |
| **Retrieval** | Theme-leak accuracy | **100%** (5/5) | In-corpus noise queries: theme neurons must not appear in top-5 |
| **Retrieval** | Abstain accuracy | **100%** (5/5) | True off-topic queries with abstention enabled |
| **Task** | Pass rate | **17/23 (74%)** | Live-brain `answer_facts` gate; fixture drift vs 0.3.2’s 23/23 — not the public claim |
| **Latency smoke** | recall / pack p95 | **2.1 / 3.3 ms** | Ephemeral tiny brain; targets ≤150 / ≤250 ms |
| **Latency loaded** | recall / pack p95 | **808 / 224 ms** | Live brain; targets ≤1200 / ≤1500 ms |

### Cursor-framed pack-vs-dump (`compare` / `compare_v1`)

Same metric class as the Antigravity Live section below: **full multi-file dump** vs
`brainkm context_pack` (**no in-built agent tool loop** — Grep/Read/edit not in the
loop). Cursor-shaped queries (token budget, MCP dispatch, Graphify routing, session
snapshot) live in `compare_v1`. **Not** the Cursor full-agent endtask suite
([2026-07-30-endtask-cursor-core](benchmarks/2026-07-30-endtask-cursor-core.md)).

| Scenario | Without (dump) | With (pack) | Savings |
|----------|----------------|-------------|---------|
| token_budget | 9987 | 607 | 16.5× |
| mcp_dispatch | 7014 | 457 | 15.3× |
| graphify_routing | 11074 | 898 | 12.3× |
| session_snapshot | 5241 | 347 | 15.1× |

Average **~94% token reduction (~15.7×)** across 4 Cursor-framed scenarios.
Reproduce: `brainkm bench run compare`.

> #### End-task A/B scorecard — Cursor Core (`endtask_protocol/1.1`, publish set `endtask_h2h/2`)
>
> **Finding:** On Core (36 live `composer-2.5` runs, `--require-mcp`, with-arm
> `WITH_ARM_MCP_PREFIX` + `setting_sources=project`), brainkm went **18/18 pass**
> vs **17/18 without**, with **mcp_ok 18/18** on both arms (with mean **MCP_db=1.4**).
> Session prompt tokens: **−30%** (71 115 vs 102 091) — distinct from the ~94%
> pack-vs-dump figure above.
>
> | Arm | Pass | Mean tools | Mean MCP_db | mcp_ok | Mean prompt tokens |
> |-----|------|------------|-------------|--------|--------------------|
> | **with brainkm** | **18/18** | **9.8** | **1.4** | **18/18** | **71 115 (−30%)** |
> | without | 17/18 | 15.7 | 0.0 | 18/18 | 102 091 |
>
> Full scorecard:
> [2026-07-30-endtask-cursor-core](benchmarks/2026-07-30-endtask-cursor-core.md).
> Historical Full (−5%, pre-protocol) and pre-routing Core (9/18 mcp_ok) are under
> [End-task history](#end-task-history-preserved).

### Antigravity Live Benchmark (Token Usage Reduction & Quality Run)

Pack-vs-dump on Antigravity-shaped queries (`.agents/` / HTTP MCP `serverUrl` / distill adapter): **full multi-file dump** vs `brainkm context_pack`. Same metric class as `compare` above — **not** a full-agent suite with Grep/Read/edit (that is Path A endtask).


| Scenario ID | Query / Intent | Without Brain | With Brain (Pack Text) | Payload (JSON) | Token Reduction | Savings | Key Artifact |
|-------------|----------------|---------------|------------------------|----------------|-----------------|---------|--------------|
| `antigravity_class_lookup` | `AntigravityDistillAdapter build_antigravity_hook_stdout` | 20,293 | 733 | 1,102 | **96.4%** | **27.7×** | [2026-07-21-antigravity-live](benchmarks/2026-07-21-antigravity-live.md) |
| `antigravity_pipeline` | `antigravity hook distill transcript integration` | 20,293 | 1,084 | 1,550 | **94.7%** | **18.7×** | [2026-07-21-antigravity-live](benchmarks/2026-07-21-antigravity-live.md) |
| `antigravity_mcp_config` | `antigravity mcp serverUrl hooks .agents/mcp_config.json` | 20,293 | 1,132 | 1,585 | **94.4%** | **17.9×** | [2026-07-21-antigravity-live](benchmarks/2026-07-21-antigravity-live.md) |

Average **95.2% token reduction (~21.4× savings)** across Antigravity scenarios while surfacing exact AST nodes and historical project decisions without noise. Full report: [docs/benchmarks/2026-07-21-antigravity-live.md](benchmarks/2026-07-21-antigravity-live.md).

> #### End-task A/B scorecard — Antigravity Core (`endtask_protocol/1`, publish set `endtask_h2h/2`)
>
> **Finding:** On the **same Core 6-task subset** as Cursor (36 live `agy --print`
> runs, Cursor regex/checker graders, `--home-mcp-swap --require-mcp`, with-arm
> MCP prefix), brainkm went **18/18 pass vs 12/18 without**, with **mcp_ok 18/18**
> on both arms (with mean **MCP_db=1.7**, without **0**).
> Tokens: **N/A** (AGY print-mode does not expose session usage).
>
> | Arm | Pass | Mean tools | Mean MCP_db | mcp_ok | Tokens |
> |-----|------|------------|-------------|--------|--------|
> | **with brainkm** | **18/18** | 15.2 | **1.7** | **18/18** | N/A |
> | without | 12/18 | 16.1 | 0.0 | 18/18 | N/A |
>
> Significance: **quality + proven MCP use** on a uniform fixture — not pack-vs-dump.
> Card: [2026-07-22-endtask-antigravity-core](benchmarks/2026-07-22-endtask-antigravity-core.md).
>
> #### Cross-host Core (`endtask_h2h/2`)
>
> | Host | Tier | Pass with / without | mcp_ok | Mean prompt tokens |
> |------|------|---------------------|--------|--------------------|
> | Cursor | Core (`1.1`) | **18/18** / 17/18 | **18/18** | **−30%** (71 115 vs 102 091) |
> | Antigravity | Core (`1`) | **18/18** / 12/18 | **18/18** | N/A |
> | Claude / Codex | — | pending | — | — |
>
> Compare pass/tools/mcp across hosts; **% token reduction only** where
> `tokens_supported=true` (Cursor today). Full tier (120) remains optional stretch.

### Pack-vs-dump proxy script (Antigravity-themed)

[`brainkm/scripts/antigravity_trajectory_bench.py`](../brainkm/scripts/antigravity_trajectory_bench.py)
re-runs the same **dump vs `context_pack`** economics on AGY-shaped questions.
Default `--mode tokens-only` needs no API key. Optional `--mode llm` calls Groq/Gemini
and only scores keyword hits when an arm **finishes** (413 / rate-limit dump failures
are failures, not “0% decisions after 5 tool hops”).

Latest: [2026-07-22-antigravity-trajectory-live.md](benchmarks/2026-07-22-antigravity-trajectory-live.md).

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

## Noise control and policy surfacing (since 0.3.2)

Product fixes behind the split retrieval metrics and redaction task pass (landed in
**0.3.2**; still in force on **0.9.0**):

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
