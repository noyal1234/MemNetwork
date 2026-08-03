# brainkm vs agentmemory — comparison notes

Apples-to-apples where possible. Vendor figures we did not reproduce are labeled.

## Headline (brainkm product metric): recall@budget

brainkm injects a **hard ≤1500-token** context pack. The metric that matches that
contract is **recall@budget**: is any gold id present in `truncation.included_ids`?
Companion: **pack noise** (fraction of pack ids that are non-gold).

| Corpus | recall@budget | Mean pack tokens | Pack noise |
|--------|---------------|------------------|------------|
| CMA v3 (coding-agent fixture) | **0.810** | 175 / 1500 | 0.721 |
| LongMemEval-S full 500 (fts-blob) | **0.892** | 373 / 1500 | 0.724 |

agentmemory’s published LongMemEval protocol does **not** report a hard pack budget
(their cost model cites ~1.9k tokens/session). Until a competitor is scored under the
same 1500-token cap, treat recall@budget as an on-our-terms claim with clear caveats —
not a leaderboard win by fiat.

## Shared protocol footnote: LongMemEval-S `recall_any@K`

Both projects measure **`recall_any@K`** on the cleaned LongMemEval-S haystacks
([xiaowu0162/longmemeval-cleaned](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned)):
index sessions for one question, retrieve with the question text, check whether any
gold session id appears in the top-K. **No LLM judge** — this is retrieval only.

| System | Mode | R@5 | R@10 | MRR | Notes |
|--------|------|-----|------|-----|-------|
| **agentmemory** (published) | BM25 + MiniLM | **0.952** | 0.986 | 0.882 | Their measured result |
| agentmemory (published) | BM25-only | 0.862 | 0.946 | 0.715 | Their fallback |
| **brainkm** (2026-07-19) | FTS blob (dual-grain default) | **0.934** | 0.962 | 0.861 | Full 500; [artifact](2026-07-19-longmemeval-s-full.md) |
| brainkm (2026-07-19 midday) | FTS chunked | 0.908 | 0.926 | 0.834 | Historical; use `--chunked` |
| brainkm hybrid-dual-grain | Blob FTS + chunk MiniLM | 0.729 | 0.729 | 0.708 | Stratified n=48; did not beat FTS |

Caveats:

- Mem0 / Letta LoCoMo numbers are a **different dataset** — not shown as head-to-head here.
- Official LongMemEval **QA accuracy** (retrieve + generate + GPT judge) is out of scope for brainkm v1.
- Dual-grain: whole-session blobs for FTS; optional chunk embeddings for `--semantic`.
  Session-level `fts_primary` fusion. Full-500 hybrid deferred until stratified beats FTS.

Reproduce:

```bash
export LONGMEMEVAL_PATH=~/.cache/brainkm/longmemeval_s_cleaned.json
brainkm bench run longmemeval --stratify 0            # full FTS blob + recall@budget
brainkm bench run longmemeval --stratify 8 --semantic # dual-grain hybrid sanity
```

## What brainkm measures that chat-memory vendors usually do not

| Axis | Suite | Why it matters for coding agents |
|------|-------|-----------------------------------|
| **recall@budget** | `cma`, `longmemeval` | Gold-in-pack under hard 1500 tokens |
| Pack noise | `cma`, `longmemeval` | Honesty companion to recall@budget |
| Abstention / theme-leak | `retrieval`, `cma` | Keyword collisions must not inject junk |
| Compaction survival | `compaction` canary | Truth survives host summarize |
| Code-graph structure | `scorecard`, `cma` multi_hop | Blast-radius / traverse quality |
| Supersede / staleness | `staleness` | Updated facts outrank archived ones |
| Scale curve | `scale` | R@5 + p95 latency at 1k/10k/50k |
| Cost model | `cost` | Injected tokens/session + $/yr estimate |

## Coding-agent diagnostic (CMA) — regression gate

CMA is a **self-authored coding-agent corpus** (neurons + edges + supersedes). Use it to
diagnose abilities; do **not** present CMA micro-avg as “LongMemEval R@5”.

Ability micro-avg is currently **saturated (100%)** — treat it as a **regression gate**,
not a public claim. Quote **recall@budget** + hard-slice lift instead.

Latest: [2026-07-31-cma.md](2026-07-31-cma.md) — recall@budget **0.810**,
hard-slice brain **1.00** vs BM25 **0.55**, mean pack **~175**/1500, micro gate **100%**.
Prior (0.5.0): [2026-07-19-cma-v3-budget.md](2026-07-19-cma-v3-budget.md).

## Product shape (why scores diverge)

| | brainkm | agentmemory |
|--|---------|-------------|
| Primary store | Project SQLite brain + Graphify AST | Local memory engine + MCP |
| Pack budget | Hard ≤1500 tokens | ~1.9k tokens/session (their model) |
| Code graph | First-class `traverse` | Not the same product axis |
| Hosts | Cursor / Claude / Antigravity hooks | Broad MCP client list |

## End-task cost model — brainkm wins long, loses short

Hosts bill `input_tokens` cumulatively across model round-trips, so end-task cost is
`a*R + b*R(R-1)/2` for `R` rounds: `a` = context re-sent every round, `b` = tokens each
tool result adds to all later rounds. Fitting the Codex Core runs (n=36) separates the two:

| Arm | `a` — fixed per round | `b` — per tool result |
|-----|----------------------|-----------------------|
| with brainkm | 16,914 | **2,864** |
| without | 7,603 | 11,235 |

brainkm trades **+9.3k fixed per round** (MCP tool schemas ~2.7k, rules file ~1.6k,
SessionStart injection, MCP prefix) for **−8.4k per tool result** — the ≤1500-token pack
cap replacing multi-thousand-token grep/read dumps. Crossover is ~3 tool calls: below it
brainkm costs more, above it the gap widens in brainkm's favour (at 7 tools, 216k vs 375k).

**Consequence for reporting:** never quote cumulative `mean_prompt_tokens` across arms
without the round count — it conflates context size with tool-call count. `endtask_protocol/1.2`
reports `tokens/round` alongside it for this reason. A short-task fixture will always flatter
the no-memory arm.

## Deferred

- Full LoCoMo / BEAM runs (wrong shape for a project brain).
- Official LongMemEval QA + LLM judge.
- Running agentmemory’s TypeScript harness against brainkm (nice-to-have).
- End-task **Full** tier (120) and Claude host — Core H2H for Cursor +
  Antigravity + Codex is published (`endtask_h2h/3`; see [BENCHMARKS.md](../BENCHMARKS.md)).
- **Codex `endtask_v1` probe kept unpublished** — [2026-08-02 card](2026-08-02-endtask-codex-core.md).
  Repo-answerable Core lets a strong model short-circuit with ~1.5 tools (no memory
  headroom). Published Codex card uses `endtask_memory_v1` instead:
  [2026-08-03-endtask-codex-memory-core](2026-08-03-endtask-codex-memory-core.md)
  (**18/18 vs 2/18**, mcp_ok 18/18, **−17%** cum. / **−10%** per round).
- Full-500 `--semantic` until stratified hybrid ≥ FTS.
