# MemNetwork (brainkm) — AI Project Brief

> **Purpose:** Single source of truth for what MemNetwork is, how it is built, and what to implement next.  
> **Repo:** `MemNetwork/` — Python package `brainkm` (MCP server + CLI).  
> **MCP server name:** `brainkm` · **Storage:** `.brain/brain.db` per target project.  
> **User-facing feature catalog:** [FEATURES.md](FEATURES.md)

---

## 1. Product vision

**MemNetwork** is a **local, project-scoped augmented brain** for Cursor, Claude Code, and Antigravity (Codex connect supported). It captures architectural decisions from chat and plans, maps code structure via an AST graph, and injects bounded context so agents stop re-reading files and re-explaining past decisions.

| Principle | Meaning |
|-----------|---------|
| **Zero-LLM default (T0)** | Rule-based distill, FTS5 BM25, Graphify AST — no local Ollama, no cloud API required |
| **User-chosen distill** | `capture.distill_mode`: `cursor` \| `claude` \| `antigravity` \| `ollama` \| `groq` \| `rules` (legacy `mcp` → `claude`) |
| **Compaction-aware** | PreCompact / synthetic-precompact handover + SessionEnd / idle Stop so truth survives host compaction |
| **Inspectable** | Every memory is a SQLite row or markdown export — `forget`, export/import, consolidate |
| **Bounded tokens** | 1500-token hard cap on agent-facing packs (`pack_text` + compact MCP JSON); structural retrieval over file dumps |
| **Complement Cursor** | Does not replace @codebase or Cursor Memories — stores **project-specific** decisions |

**Primary jobs:**

1. Remember why we chose X over Y (decisions, pivots, plan changes).
2. Navigate code structure without re-reading entire modules (`context_pack`, `traverse`).
3. Survive long sessions and compaction with external recall storage.
4. Self-learn useful tool chains as procedure nodes (V2).

---

## 2. System context

```mermaid
flowchart LR
  subgraph cursor [Cursor IDE]
    Chat[Chat window]
    Hooks[SessionStart End PreCompact]
    MCP[MCP client]
  end

  subgraph brainkm_pkg [brainkm package]
    Server[MCP server]
    Tools[8 MCP tools]
    Services[services layer]
    Adapters[adapters layer]
  end

  subgraph storage [Per-project .brain]
    DB[(brain.db SQLite)]
    Graph[graphify-out/graph.json]
  end

  Hooks --> Server
  MCP --> Server
  Server --> Tools --> Services --> Adapters
  Adapters --> DB
  Adapters --> Graph
  Services -->|"injection pack"| Chat
```

| Layer | Technology | Role |
|-------|------------|------|
| **Memory** | SQLite FTS5 BM25 | Neurons (`kind=memory`) — facts, decisions, rules |
| **Code graph** | Graphify AST adapter | `code` nodes, import/call edges |
| **Temporal** | `valid_from` / `valid_until`, `supersedes` | Evolving facts without full GraphRAG |
| **MCP** | `mcp` SDK stdio **or** localhost HTTP (`brainkm serve`) | 8 tools: remember (pin/correct), recall, context_pack, session_status, traverse, forget, brain_stats, graph_sync |
| **CLI** | Typer | install, serve, connect, doctor, export, bench, repair, handover, review, hygiene, migrate, configure |
| **TUI** | Textual (optional `[tui]` extra) | `brainkm configure` — guided app checkboxes, Start Brain, dashboard, config editor, actions |
| **Optional T1** | sqlite-vec + ONNX MiniLM | Semantic search when `semantic: true` |
| **Optional T2** | Cursor / Ollama / Groq at SessionEnd | `distill_mode: cursor \| ollama \| groq` |

---

## 3. Repo layout

```
MemNetwork/
├── .venv/                         # Python venv (gitignored)
├── AGENTS.md                      # Agent entry point
├── docs/
│   ├── AI_PROJECT_BRIEF.md        # This file
│   ├── CLI_COMMANDS.md            # Full CLI catalog
│   ├── INSTALL.md                 # Clone + MCP setup
│   └── TUI_APP_PLAN.md            # brainkm configure (shipped)
├── .cursor/
│   ├── skills/memnetwork-backend/
│   └── rules/memnetwork-*.mdc
├── brainkm/
│   ├── pyproject.toml             # Source of truth for deps
│   ├── scripts/setup_dev.sh
│   ├── brainkm/
│   │   ├── cli.py                 # Typer CLI
│   │   ├── config.py              # get_settings()
│   │   ├── logging_config.py
│   │   ├── models/
│   │   │   ├── brain_config.py    # .brain/config.json schema
│   │   │   └── schemas.py         # MCP tool I/O
│   │   ├── tools/                 # MCP handlers
│   │   ├── services/              # memory, search, budget, learning, …
│   │   ├── adapters/              # graphify, transcripts, distill, redaction
│   │   ├── tui/                   # Textual configure app (optional [tui])
│   │   └── db/                    # SQLite + migrations
│   └── tests/
└── README.md
```

**Per target project** (after `brainkm install`):

```
.brain/
├── brain.db              # gitignore
├── config.json           # optional commit
├── graphify-out/
└── exports/
```

---

## 4. MCP tool contract (V1 / current)

**Package version:** `0.4.2`

| Tool | Purpose |
|------|---------|
| `remember` | **Pin** durable project truth or **correct** a wrong auto-capture (hooks are the primary capture path); auto-links path mentions |
| `recall` | FTS5 + graph activation; abstain on low confidence (percentile default P10); bodies capped to `budget.total_tokens` |
| `context_pack` | Task-specific compiled pack (graph + neurons + procedures). Prefer before 3+ file reads; for pure blast-radius use `traverse`. Default MCP payload is lean (`pack_text` + truncation IDs); pass `include_structured=true` for full neuron arrays |
| `session_status` | Read/write session context neuron |
| `traverse` | Focused AST neighborhood (callers/callees/imports). Defaults: `direction=both`, structural edges; returns `resolved_id` + `hint` on empty |
| `forget` | Soft-archive node (`valid_until`) + cascade edges |
| `brain_stats` | Health summary: neuron/graph counts, MCP usage (7d), abstention rate, dead-neuron count; optional `session_id` adds per-session MCP/hit/snapshot/distill fields |
| `graph_sync` | Queue or force Graphify extract+import |

CLI-only (not MCP): `install`, `serve`, `connect`, `doctor`, `export`, `bench`, `repair`, `handover`, `review`, `hygiene`, `migrate`, `configure`.

Shared localhost brain: prefer **`brainkm configure`** (multi-app → Start Brain). Power path: `brainkm serve` + `brainkm connect <client> --http` so Cursor / Claude / Antigravity / Codex share one HTTP MCP process and `.brain/brain.db`. Antigravity HTTP MCP uses `serverUrl`. Hooks remain the primary memory writers (`capture.auto_observe`).

---

## 5. Host ecosystem boundaries

MemNetwork **complements** Cursor, Claude Code, and Antigravity — it does not replace built-in indexing, user memories, or static rules. One `brainkm` MCP server per project; do not stack Mem0, Pinecone, or other memory layers on top.

| Client | MCP path | Hooks / rules |
|--------|----------|---------------|
| Cursor | `.cursor/mcp.json` | `.cursor/hooks.json`, `.cursor/rules/brainkm.mdc` |
| Claude Code | `.mcp.json` | `.claude/settings.json`, `.claude/rules/` |
| Antigravity | `.agents/mcp_config.json` (HTTP: **`serverUrl`**) | `.agents/hooks.json`, `.agents/rules/` |

### 5.1 System boundaries

| System | Scope | What it stores | brainkm rule |
|--------|-------|----------------|--------------|
| **Cursor Memories** | Cross-project user preferences | "I prefer tabs over spaces", global coding style | **Do not duplicate.** brainkm stores **this project's** decisions, rules, and pivots only |
| **Cursor Rules** (`.cursor/rules/`) | Static team policy | Always-on conventions, lint rules, architecture mandates | **Complement.** Rules = policy; neurons = dynamic learned context. `brainkm install` scans rules and warns on topic overlap |
| **@codebase** | Semantic code index (embeddings) | Source files, symbols, natural-language code search | **Complement, not replace.** Consult `context_pack` / `traverse` first for navigation, **then verify in source** before editing |
| **Chat compaction** | Lossy in-window summarize (~35% DMR recall) | Compressed chat history inside the window | **Work with it.** PreCompact handover + SessionEnd capture → neurons survive in `brain.db` |
| **Agent transcripts** | Raw JSONL chat history | Full conversation logs under `agent-transcripts/` | **Distill, don't inject.** Search via `session_fts`; auto-distill to neurons at SessionEnd/PreCompact |

### 5.2 @codebase vs brainkm — when to use which

| Question type | Use first | Why |
|---------------|-----------|-----|
| "Where is auth middleware defined?" | **@codebase** or `context_pack` | Semantic/symbol lookup across source |
| "Why did we choose JWT over session cookies?" | **`recall`** | Decision lives in chat/plan distill, not in code index |
| "What connects `AuthService` to `UserRepo`?" | **`traverse`** | Focused AST neighborhood (callers/callees/imports) |
| "What failed last time we touched payments?" | **`recall`** (subtype `error`) | Known failure modes are neurons |
| Read 5+ files to understand one module | **`context_pack`** then targeted reads | Bounded pack vs multi-file dumps; never skip reading source you will change |

**Do not** wire local LLM into `recall` or `context_pack` to compete with @codebase — that duplicates Cursor's index badly and destroys the token-efficiency story.

### 5.3 Frozen snapshot vs live recall

Injection (SessionStart hook) and tool calls (MCP) use **different data paths** on purpose:

| Path | Data source | Updates mid-session? |
|------|-------------|----------------------|
| SessionStart injected pack | Frozen snapshot (`session_snapshots`) | **No** — preserves Cursor prefix cache |
| Agent calls `recall` | Live `brain.db` | Always fresh |
| Agent calls `context_pack` | Live `brain.db` | Always fresh |
| Agent calls `remember` | Writes live DB | Visible to next `recall` in same session; **not** added to frozen pack |

Controlled by `injection.frozen_snapshot: true` (default). PostCompact snapshot refresh is **V1.5**.

### 5.4 What MemNetwork wins on (vs @codebase alone)

- **Decision/pivot memory** — "why X not Y" from chat and plans
- **Bounded `context_pack`** — path-labeled snippets under the 1500-token agent-facing cap (vs multi-file reads)
- **Cross-session chat distill** — survives compaction via PreCompact handover
- **Procedure learning** (V2) — promote repeated co-activated context + observed tool sequences into `kind=procedure` stubs (scaffolding; not Hermes-grade skill self-improvement)

---

## 6. Related memory systems (MemGPT / Mem0 / Claude)

MemNetwork implements **MemGPT-style virtual context** without LLM self-paging — hooks and deterministic retrieval replace agent-managed memory paging.

```mermaid
flowchart TB
  subgraph inWindow [Main context — MemGPT RAM equivalent]
    CursorChat[Cursor chat window]
    InjectedPack[brainkm pack max 1500 tokens]
  end

  subgraph external [External context — MemGPT disk equivalent]
    BrainDB[.brain/brain.db]
    Sessions[session_chunks + session_fts]
    Neurons[memory neurons]
    CodeGraph[code graph Graphify]
  end

  subgraph compaction [Three-layer compaction defense]
    L1[SessionEnd capture]
    L2[PreCompact handover]
    L3[SessionStart injection]
    CursorCompact[Cursor lossy compact]
  end

  CursorChat -->|near limit| CursorCompact
  L2 -->|before| CursorCompact
  L1 --> Neurons
  L2 --> Neurons
  BrainDB --> Neurons
  BrainDB --> Sessions
  BrainDB --> CodeGraph
  BrainDB -->|recall context_pack| InjectedPack
  InjectedPack --> CursorChat
  L3 --> InjectedPack
```

### 6.1 MemGPT mapping ([arXiv:2310.08560](https://arxiv.org/abs/2310.08560))

| MemGPT tier | MemNetwork equivalent | Paging controlled by |
|-------------|----------------------|---------------------|
| Main context | Cursor chat + injected pack (≤1500 tokens) | Hooks + budget — **not LLM** |
| Recall storage | `session_chunks` + `session_fts` | SessionEnd + PreCompact capture |
| Archival storage | `nodes` where `kind=memory` | Hooks + distill primary; MCP `remember` for pin/correct |
| Self-editing memory | `supersedes` edges, co-activation (V2), pin via `remember` | Hooks + learning loop + agent corrections |

**Adopt:** External store beats recursive summarization — DMR benchmark ~**93.4%** recall vs ~**35.3%** for lossy summarize.

**Reject:** LLM-managed paging (MemGPT/Letta) — every page-in is an LLM call; incompatible with zero-LLM default and token budget.

### 6.2 Mem0 mapping ([arXiv:2504.19413](https://arxiv.org/abs/2504.19413))

| Mem0 pattern | MemNetwork | Phase |
|--------------|------------|-------|
| Multi-signal fusion (vector + BM25 + entity) | FTS5 BM25 + 2-hop graph activation + optional sqlite-vec RRF | V1 / T1 |
| Session decomposition | Split transcripts into user/assistant rounds before distill | V1 |
| Fact-augmented keys | Auto-tags on distill for BM25 indexing | V1 |
| ADD-only audit trail | `audit_log`; `forget` → `valid_until` (soft archive) | V1 |
| Async extraction | SessionEnd / PreCompact run after agent responds | V1 |
| ADD-only without supersede | **Reject** — use `supersedes` for knowledge updates (LongMemEval) | — |

**Reject:** Hosted Mem0 API — one local MCP server only; no cloud vector layer.

### 6.3 Claude / Cursor compaction mapping

| Claude / Cursor primitive | MemNetwork equivalent |
|-------------------------|----------------------|
| Compaction (lossy summarize) | Work **with** it — PreCompact `brainkm handover` captures before loss |
| Tool-result clearing | `context_pack` delivers smallest verifiable pack upfront |
| Built-in memory tool | `brain.db` neurons + hooks / `recall` (+ `remember` pin) |
| Post-compact amnesia | SessionStart frozen injection + live `recall` on demand |

**Three-layer defense:** (1) SessionEnd continuous capture → (2) PreCompact handover → (3) SessionStart injection after compact.

### 6.4 System comparison

| System | Infra | LLM per memory op | Compaction strategy | Best for |
|--------|-------|-------------------|---------------------|----------|
| MemGPT/Letta | Server + vector DB | Yes (self-paging) | LLM-managed | Hosted research agents |
| Mem0 | Cloud vector + graph | Yes (async extract) | None (external only) | SaaS memory layer |
| Zep/Graphiti | Neo4j / cloud | Yes per episode | Temporal KG | Enterprise multi-tenant |
| Claude/Cursor compact | Built into IDE | Yes (summarize) | Lossy in-window | Session survival only |
| **MemNetwork** | SQLite local | **cursor \| ollama \| groq \| rules** at SessionEnd/PreCompact only | **PreCompact + SessionEnd + injection** | Solo dev project brain |

### 6.5 Research patterns — adopt vs defer

| Paper / system | Key insight | MemNetwork stance |
|----------------|-------------|-------------------|
| MemGPT DMR | External recall >> summarize | **Adopt** metaphor + DMR-lite bench (V1.5) |
| Mem0 fusion | Multi-signal retrieval | **Adopt** FTS5 + graph; optional vectors (T1) |
| STAR-RAG | Seeded PPR, high token reduction | **Adopt** tag-graph 2-hop BFS (lighter than full PPR) |
| Zep/Graphiti bi-temporal KG | Episode + semantic layers | **Defer** — patterns only; too heavy for default |
| LongMemEval | Temporal knowledge updates | **Adopt** `supersedes`, not pure ADD-only |

**Rejected for V1–V3 default:** Neo4j, Pinecone, Mem0 cloud, MemGPT LLM self-paging, full temporal GraphRAG, Postgres.

---

## 7. BrainConfig (`.brain/config.json`)

Validated by `BrainConfig` in `brainkm/models/brain_config.py`. Example: `brainkm/config.example.json`.

Key fields:

- `project_roots` — monorepo roots the brain spans
- `budget.total_tokens` — default 1500 (enforced on `pack_text` and lean MCP payload; structured duplicates are opt-in)
- `capture.plan_files` — ingest `.cursor/plans/*.plan.md`
- `capture.distill_mode` — `rules` \| `cursor` \| `ollama` \| `groq` (see local vs cloud note below)
- `ollama.model` — default `qwen2.5:3b`; optional `auto_select_model` via `brainkm ollama doctor`
- `groq.model` — default `llama-3.3-70b-versatile`; API key via `GROQ_API_KEY` env / `.env`
- `injection.frozen_snapshot` — SessionStart pack frozen; mid-session `remember` does not mutate injection
- `injection.max_recalls_per_turn` — default **3** (30s window)
- `recall.abstain_mode` / `recall.abstain_percentile` — return `[]` on low-confidence matches (default percentile **0.10** / P10; least-strict of live/rolling/calibration thresholds)
- `handover.precompact_enabled` — PreCompact hook distill
- `handover.precompact_distill_timeout_seconds` — default **30** (avoids silent fall-through to noisy `rules` during handover)

### Local vs cloud distill

| Mode | When to choose | Requirements |
|------|----------------|--------------|
| `rules` | Zero-dependency default; offline; no API key | None |
| `ollama` | Privacy / offline LLM distill on your machine | Ollama daemon + model (`brainkm ollama doctor`) |
| `groq` | Higher quality / speed without local GPU/CPU load | `GROQ_API_KEY` + network (`brainkm groq doctor`) |
| `cursor` | Cursor agent CLI (`agent -p`) when available; else Cursor-aware heuristic distill of cleaned transcripts | Cursor session hooks; optional `agent` CLI |

T0 remains **rules** — cloud and local LLM distill are opt-in. Never put API keys in `.brain/config.json` or neurons.

All distill modes share Cursor chrome cleaning (`clean_cursor_text` / `is_distill_noise`) before extraction. LLM modes return `{"neurons":[...]}`; subtypes are validated in code. Capture fingerprints title+body to skip duplicates; SessionStart/PreTool injection re-runs a noise gate so junk never reaches the agent.

---

## 8. Implementation status

| Phase | Status | Deliverables |
|-------|--------|--------------|
| **V0** | Done | Scaffold, AGENTS.md, BrainConfig, tests, cursor rules |
| **V1** | Done | SQLite brain, hooks, install, capture/handover, Graphify import + sync, frozen snapshot, MCP tools, adaptive abstention |
| **V1.5** | Done | bench suites, repair + abstention recalibrate, export/import merge, PostCompact refresh |
| **V2** | Done | Tool registry, review queue, confidence-gated review, PostToolUse learning loop, session-scoped co-activation procedure promotion (tool-sequence body + context seeds) |
| **TUI** | Done | `brainkm configure` Textual app (guided multi-app wizard, Start Brain, dashboard, config editor, actions); optional `[tui]` extra — see [TUI_APP_PLAN.md](TUI_APP_PLAN.md) |
| **0.2.0** | Done | End-to-end token cap on agent-facing packs; lean MCP payloads; MCP usage telemetry in `brain_stats`; distill cleaning parity + prompt fix; `brainkm hygiene`; injection-time noise gate; path-labeled code nodes |
| **0.3.0** | Done | Redaction on all neuron write paths; SessionStart/snapshot total_tokens clamp; read-tool commits via WriteQueue; session-scoped `brain_stats`; TUI SVG snapshots + ANSI-16 fallback; version discipline; hybrid RRF retrieval + PPR; intent routing; conflict supersede; pack compression/summary-first; latency bench; usage feedback; decay/consolidate; multi-client install; MCP resources/HTTP; team neurons; import `--replace` |
| **0.3.1** | Done | TUI wizard **Agent Client** step (`cursor` / `claude` / `generic`) wired to `run_install(--client)`; Cursor Agent CLI step gated on client+distill; docs/skill/CLI/TUI plan version sync |
| **0.3.2** | Done | Real ONNX MiniLM + CE rerank (opt-in `[semantic]`); wizard **Semantic Quality** consent after Hardware Doctor; typed MCP `outputSchema`; Claude JSONL capture; MCP sampling callback hook; TUI knobs for semantic/rerank/decay; BENCHMARKS local latency numbers |
| **0.4.0** | Done | Shared localhost brain: `serve` / `connect` / `doctor`, URL MCP, `/health`, TUI app checkboxes + Start Brain; Claude `.mcp.json` + Codex adapter; `capture.auto_observe` (PostToolUse / prompts / failures → capped observations → SessionEnd promote); `remember` demoted to pin/correct in rules/docs |
| **Nodal adopt** | Done | Lifecycle ladder (observation TTL, episode, `distilled_from`); `about_file`/`about_symbol` + hook file seeds; concept materializer; Seed→Expand→Diversify→Budget→Abstain; pack quotas; `consolidate --llm`; temporal supersede meta; team tags; skill pack; scorecard bench; `file-history` / `provenance` / `demo` CLI |
| **0.4.1** | Done | Claude Code silent memory parity: `.claude/settings.json` hooks + `hookSpecificOutput`; SubagentStart/Stop + Stop; Claude-default `auto_observe`; `.claude/rules` + routing skill; doctor dry-run; TUI copy/dashboard Claude hooks status; coexistence with CLAUDE.md / Auto Memory |
| **0.4.2** | Done | Antigravity first-class client (`.agents/` MCP `serverUrl` + named hooks, PreInvocation inject, synthetic precompact, idle Stop distill, AGY transcript JSONL); `distill_mode` peers `claude` (`claude -p` + live sampling) + `antigravity` (`agy -p`); legacy `mcp`→`claude`; TUI Antigravity checkbox + dashboard AGY hooks; doctor multi-path probes + `--mirror-global` |
| **CMA scorecard** | Done | Common Memory Axes public scorecard (`bench run cma`): **v3** paraphrase/noise hard slice (brain **1.00** vs BM25 **0.55**); decision/structure scorecard; LongMemEval-S footnote (full-500 FTS R@5 **0.934**; stratified MiniLM side-by-side shows FTS wins); `run_cma.sh` + dated `docs/benchmarks/` artifacts |
| **Public distribution** | **Deferred** | PyPI / `uvx` zero-clone install, trusted-publishing + public CI matrix, MCP Registry listing, Cursor deeplink — wait until repo is public and a stable version ships. Local path: `brainkm install --dev`. |
| **V3+ polish** | Ongoing | Packaged ONNX MiniLM weights, cross-encoder reranker weights, refreshed public bench numbers after open-source |

### SQLite concurrency

Single-writer queue (`services/write_queue.py`) serializes MCP writes (remember, forget, use_count flush) with SQLITE_BUSY retry. Prefer **one** HTTP `brainkm serve` process per project when using shared multi-client; stdio remains for single-editor / CI.

---

## 9. Local development

```bash
cd MemNetwork
bash brainkm/scripts/setup_dev.sh
source .venv/bin/activate
pytest
brainkm version
```

**Python:** 3.11 or 3.12. `requires-python = ">=3.11"` in pyproject.toml.

### Graphify code graph (recommended)

Setup (heavier install OK; runtime stays light — MCP never blocks on extract):

```bash
pip install -e "./brainkm[dev,graphify]"   # includes graphifyy in same venv as brainkm
brainkm install --dev                      # first sync attempted automatically
brainkm graph status                       # confirm graph_available + node count
```

| Command | When |
|---------|------|
| `brainkm graph sync` | First time, after large refactors, after `git pull` |
| `brainkm graph sync --skip-extract` | Re-import existing `graphify-out/graph.json` only |
| `brainkm graph status` | Binary found?, staleness, last import |

**Auto-sync (default on):** PostToolUse Write/Edit touches `.brain/graph_sync.requested`; the long-lived MCP server debounces background extract+import (60s debounce, 5m min interval). SessionEnd runs **import-only** fallback when `graph.json` is newer than last import.

**Multi-IDE filesystem watch (opt-in):** set `"graphify": { "auto_sync": { "watch_filesystem": true } }`, then **restart the MCP server**. While MCP is running, source-file changes from any editor (or `git checkout`) request the same sync flag — hard-ignores `.git` / `.brain` / `graphify-out` / `.venv` / etc., honors `.graphifyignore`, and only reacts to common source extensions. Restart MCP after toggling the flag (config is read at scheduler start).

**Boundaries:** Graphify produces AST structure; brainkm imports with `code_only: true` via `adapters/graphify.py`. Does not replace Cursor `@codebase`. Copy `.graphifyignore.example` → `.graphifyignore` to keep extract offline (no docs/LLM pass).

Disable auto-sync: `"graphify": { "auto_sync": { "enabled": false } }`. Skip install sync: `brainkm install --no-graph`.

### Optional Textual dashboard

```bash
pip install -e "./brainkm[tui]"
brainkm configure [--project-dir PATH]
```

Guided setup (pick coding apps → silent stdio or shared brain + **Start Brain**), Semantic Quality consent, live status (Ollama / Groq / graph / review), validated config editing, and in-process action runners. Design + acceptance notes: [TUI_APP_PLAN.md](TUI_APP_PLAN.md). Command catalog: [CLI_COMMANDS.md](CLI_COMMANDS.md).

---

## 10. Architecture layers (mandatory)

```
MCP tool (tools/) → Service (services/) → Adapter (adapters/) → SQLite (db/)
```

- Tools: validate Pydantic I/O, call services, enforce token budget.
- Services: business logic — memory, search, budget, snapshot, learning.
- Adapters: Graphify, transcripts, plans, redaction, optional LLM distill.
- DB: WAL mode, migrations, FTS5 sync.

Read `.cursor/rules/memnetwork-architecture.mdc` for full rules.
