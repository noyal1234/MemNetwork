<div align="center">

<img src="docs/assets/banner.svg" alt="MemNetwork" width="960" />

# MemNetwork

**Local project memory for agentic coding IDEs.**

One SQLite brain. Six MCP tools. Thin host adapters.  
The `brainkm` package remembers *why* you chose something, maps how your code connects, and injects bounded context — so agents stop re-reading files and re-explaining past decisions, even after chat compaction.

[![Version](https://img.shields.io/badge/version-0.8.1-3d9a8b?style=flat-square)](brainkm/pyproject.toml)
[![Python](https://img.shields.io/badge/python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](brainkm/pyproject.toml)
[![License](https://img.shields.io/badge/license-Apache%202.0-red?style=flat-square)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-6%20tools-1a2332?style=flat-square)](docs/FEATURES.md)
[![Footprint](https://img.shields.io/badge/idle-~55--70MB%20RAM-2d6a4f?style=flat-square)](docs/benchmarks/2026-07-21-footprint.md)

[Features](docs/FEATURES.md) · [Install](docs/INSTALL.md) · [Benchmarks](docs/BENCHMARKS.md) · [Architecture](docs/AI_PROJECT_BRIEF.md) · [Security](docs/SECURITY.md)

</div>

---

## Table of contents

- [Why MemNetwork](#why-memnetwork)
- [Demo](#demo)
- [Features](#features)
- [How it works](#how-it-works)
- [Quick start](#quick-start)
- [Usage](#usage)
- [Benchmarks](#benchmarks)
- [Documentation](#documentation)
- [Status](#status)
- [Contributing](#contributing)
- [License](#license)

---

## Why MemNetwork

Long agent sessions burn tokens and lose context. Compaction summarizes the chat and drops decisions you already debated. Host Memories and rules help — but they are not a searchable, graph-aware **project brain**.

- **Stop re-explaining pivots** — “we chose JWT over sessions” lives in neurons, not only in chat history
- **Stop dumping whole modules** — bounded `context_pack` (≤1500 tokens) instead of five-file reads
- **Survive compaction** — PreCompact handover + SessionEnd capture keep truth in SQLite
- **One brain, many hosts** — same `.brain/` across Cursor, Claude Code, Antigravity, Codex, and any MCP client
- **Lightweight local runtime** — shared `brainkm serve` idles **~55–70 MB RAM** / **≪1% CPU**; active MCP rounds peak ~**110 MB**, then CPU drops again. Method + numbers: [footprint](docs/benchmarks/2026-07-21-footprint.md) (optional configure TUI is separate, ~160 MB)

MemNetwork is **not** a Cursor plugin and **not** a second `@codebase`. Cursor is one first-class host (deepest today while we dogfood there). The brain and MCP API stay the same; adapters fill host gaps.

---

## Demo

Optional guided UI (`brainkm[tui]` → `brainkm configure`):

<p align="center">
  <img src="docs/assets/tui-wizard.svg" alt="brainkm configure wizard" width="48%" />
  <img src="docs/assets/tui-dashboard.svg" alt="brainkm configure dashboard" width="48%" />
</p>

<p align="center"><sub>Guided setup is optional. Explore the graph anytime with core <code>brainkm viz</code> — no extra install.</sub></p>

<!-- Future: animated GIF of `brainkm configure` (vhs / ScreenToGif) -->

---

## Features

### Remember project truth
- Hooks + `auto_observe` fill the brain (SessionEnd distill, PostToolUse observations)
- Neurons for facts, decisions, rules, and known errors — inspectable SQLite rows
- Supersede / conflict handling so new truth replaces old
- `remember` is **pin / correct / archive only** — not the everyday store path

### Navigate code structure
- Graphify AST graph: files, classes, functions, import/call edges
- `traverse` for blast-radius; `context_pack` for task-scoped neighborhoods
- Auto-sync after Write/Edit (debounced)
- **`brainkm viz`** — included browser graph explorer (no optional extra)

### Survive long sessions
- SessionStart injection, PreCompact handover, SessionEnd distill
- Manual fallbacks: `brainkm handover`, `brainkm capture`

### Smart retrieval
- Zero-LLM default: FTS5 BM25 + weighted PPR graph activation
- Optional MiniLM hybrid via `[semantic]`
- Hard ≤1500-token agent-facing packs; abstention on low confidence

### Multi-host, local-first
- Adapters: Cursor · Claude Code · Antigravity · Codex · generic MCP
- **Guided TUI** (`[tui]` extra) — recommended, not required
- Secrets redacted on write and before injection — brain stays on disk
- **Small always-on footprint** — one shared localhost MCP server (**~55–70 MB** idle RSS, near-zero CPU); active tools ~**110 MB**; optional TUI separate — [measured](docs/benchmarks/2026-07-21-footprint.md)

Full catalog → [docs/FEATURES.md](docs/FEATURES.md)

---

## How it works

```mermaid
flowchart LR
  subgraph hosts [Agent IDEs]
    Cursor[Cursor]
    Claude[Claude Code]
    AGY[Antigravity]
    Other[Codex / MCP]
  end

  subgraph pkg [brainkm]
    MCP[MCP server]
    Services[Services]
    Adapters[Adapters]
  end

  subgraph brain [Per-project .brain]
    DB[(brain.db)]
    Graph[Graphify AST]
  end

  hosts --> MCP
  MCP --> Services --> Adapters
  Adapters --> DB
  Adapters --> Graph
  Services -->|"pack ≤1500 tokens"| hosts
```

| Layer | Role |
|-------|------|
| **Memory** | SQLite FTS5 neurons — decisions, rules, facts, errors |
| **Code graph** | Graphify AST neighbors for `traverse` / packs |
| **MCP** | stdio or localhost HTTP — **6** agent-facing tools |
| **CLI / TUI** | Typer core; Textual configure when `[tui]` is installed |

**Layering:** MCP tool → service → adapter → SQLite. Deep dive → [docs/AI_PROJECT_BRIEF.md](docs/AI_PROJECT_BRIEF.md)

<details>
<summary><strong>When to use which tool</strong></summary>

| Question | Use first |
|----------|-----------|
| Where is symbol X defined? | Host codebase index / Grep |
| Why did we choose X over Y? | **`recall`** |
| What calls / imports X? | **`traverse`** |
| What changed in this file recently / why? | **`trace_changes`** |
| Understand one module (3+ files) | **`context_pack`**, then verify in source |
| Pin a decision / fix bad memory | **`remember`** |
| Brain health / empty graph? | **`brain_stats`** |
| Cross-project prefs / static policy | Host Memories / rules — not brainkm |

</details>

---

## Quick start

**Prerequisites:** Python 3.11 or 3.12.

### 1. Clone and install

```bash
git clone <your-remote-url> MemNetwork
cd MemNetwork

bash brainkm/scripts/setup_dev.sh
source .venv/bin/activate
```

### 2. Configure your IDE(s)

**Recommended** — optional guided TUI:

```bash
pip install -e "./brainkm[tui]"
brainkm configure
```

- **One app** → silent memory; that host starts the brain for you (no extra terminal).
- **Two or more** → shared localhost brain; click **Start Brain** once from the TUI.

**Without TUI** — core CLI only:

```bash
brainkm install --dev --client cursor   # or claude | antigravity | codex | generic
brainkm graph sync                      # optional first code graph
brainkm doctor
```

### 3. Reload MCP and use it

Restart the IDE or reload MCP servers. Ask the agent (or call tools) using the [Usage](#usage) table below.

```bash
brainkm version   # expect 0.8.1
```

Full setup notes → [docs/INSTALL.md](docs/INSTALL.md)

### Optional extras

| Extra | What you get |
|-------|----------------|
| `[tui]` | `brainkm configure` guided wizard / dashboard |
| `[semantic]` | MiniLM hybrid retrieval (`brainkm semantic doctor`) |
| `[graphify]` | Graphify AST extract (also pulled by `setup_dev.sh`) |

`brainkm viz` needs **none** of these — it ships with core.

> **Public install:** PyPI / `uvx` one-liner is deferred until the repo is public and the installable package name is finalized. Local path today: clone + editable install. Checklist → [docs/PUBLIC_RELEASE_CHECKLIST.md](docs/PUBLIC_RELEASE_CHECKLIST.md)

---

## Usage

| Question | Tool |
|----------|------|
| Why did we choose X? | `recall` |
| What calls / imports X? | `traverse` |
| What changed in this file recently / why? | `trace_changes` |
| Understand this module without dumping files | `context_pack` |
| Pin / correct / archive memory | `remember` |
| Is the brain healthy / graph stale? | `brain_stats` |

<details>
<summary><strong>MCP tools (6)</strong></summary>

| Tool | Purpose |
|------|---------|
| `remember` | Pin / correct / archive (`action`); correct writes supersedes |
| `recall` | Hybrid search + `decision_trail`; abstains on low confidence |
| `context_pack` | Task pack under token budget; auto-queues stale graph refresh |
| `traverse` | Impact analysis: neighborhood + `impact_summary` + linked neurons |
| `brain_stats` | Health: counts, usage, abstention, dead neurons, hygiene hint |
| `trace_changes` | Live git history + uncommitted diff, joined to commit↔session↔decision links |

</details>

<details>
<summary><strong>Hosts and complementarity</strong></summary>

| Host | Role today |
|------|------------|
| **Any MCP client** | Core contract: 6 tools + optional `brainkm serve` |
| **Cursor** | Deepest maturity (hooks, PreCompact, distill) |
| **Claude Code** | First-class hooks + MCP; distill via `claude -p` |
| **Antigravity** | First-class `.agents/` MCP (`serverUrl`) + hooks; Stop distill into project `.brain/` (`--project-dir` / auto-heal); extractor via `capture.distill_mode` |
| **Codex CLI** | First-class `.codex/config.toml` + hooks; Stop → session-end; distill via `codex exec` |
| **generic** | Connect / example MCP wiring; manual capture/handover |

| Job | Prefer |
|-----|--------|
| Cross-project user prefs | Host Memories |
| Static team policy | Host rules (`CLAUDE.md`, `.cursor/rules`, …) |
| “Where is symbol X?” | Host codebase index / Grep |
| “Why did we choose X?” | **brainkm `recall`** |
| “What calls X?” | **brainkm `traverse` / `context_pack`** |
| “What changed here?” | **brainkm `trace_changes`** |
| Hosted multi-tenant memory | Mem0 / Zep — not the goal here |

</details>

---

## Benchmarks

Public comparison uses **Common Memory Axes (CMA)** — ability accuracy + pack tokens + latency — for a coding-agent project brain (not a chat-assistant leaderboard). Headline product metric: **recall@budget** (gold fact inside a ≤1500-token pack).

Latest CMA v3 budget scorecard (brainkm **0.5.0**, semantic off) — [full write-up](docs/benchmarks/2026-07-19-cma-v3-budget.md):

| Metric | Result |
|--------|--------|
| **recall@budget** | **0.833** (floor ≥0.80) |
| Mean pack tokens | **~323** / 1500 |
| Ability micro-avg (regression gate) | **100%** (hard subset **100%**) |
| Recall / pack p95 | **~13 / 18 ms** |
| vs BM25 / title-scan (full) | brain **1.00** vs **0.88** / **0.83** |
| Hard-slice lift vs BM25 | brain **1.00** vs **0.55** (**+0.45**) |
| Decision + structure | **8/8** |

Also: LongMemEval-S full-500 footnote — **recall@budget 0.892** @ ~373 tokens ([artifact](docs/benchmarks/2026-07-19-longmemeval-s-full.md)). Runtime footprint: [2026-07-21-footprint](docs/benchmarks/2026-07-21-footprint.md).

```bash
brainkm bench run cma     # public scorecard
brainkm bench run eval    # product IR + task + latency
```

Methodology and what we refuse to claim → [docs/BENCHMARKS.md](docs/BENCHMARKS.md)

---

## Documentation

| Doc | Contents |
|-----|----------|
| [FEATURES.md](docs/FEATURES.md) | Full feature catalog |
| [INSTALL.md](docs/INSTALL.md) | Clone + editable setup |
| [AI_PROJECT_BRIEF.md](docs/AI_PROJECT_BRIEF.md) | Architecture + roadmap |
| [BENCHMARKS.md](docs/BENCHMARKS.md) | CMA scorecard + eval targets |
| [CLI_COMMANDS.md](docs/CLI_COMMANDS.md) | CLI reference |
| [SECURITY.md](docs/SECURITY.md) | Redaction posture |
| [AGENTS.md](AGENTS.md) | Agent entry point |
| [brainkm/README.md](brainkm/README.md) | Package / development notes |

---

## Status

**brainkm 0.8.1** — Project brain with six MCP tools (`remember` pin/correct/archive, `recall` + decision trail, `context_pack`, `traverse` impact, `brain_stats`, `trace_changes`), first-class Cursor / Claude / Antigravity / Codex CLI hosts (Codex: `config.toml` MCP + `codex exec` distill; AGY Stop routes into the project `.brain/`), git commit↔session joins (`git-note` / post-commit hook), hardened shared HTTP, viz access tokens, and included `brainkm viz`.

- [x] Local SQLite brain + **6** MCP tools
- [x] Cursor / Claude / Antigravity / Codex adapters
- [x] Compaction survival (PreCompact + SessionEnd)
- [x] Shared HTTP MCP Bearer auth + loopback bind guards
- [x] CMA public scorecard + product eval suites
- [ ] PyPI / `uvx` one-liner (deferred — name + public repo)
- [ ] MCP Registry / host one-click installers (deferred)

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Contributions require agreeing to the [CLA](CLA.md).

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).  
Copyright © 2026 Noyal Bastin Benny.

<p align="right"><a href="#memnetwork">Back to top</a></p>
