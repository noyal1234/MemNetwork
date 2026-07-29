# brainkm — Features

**brainkm** is a local, project-scoped brain for **agentic coding IDEs** — anything that can speak MCP. One `.brain/brain.db`, six tools, and thin host adapters. It remembers *why* you chose something, maps how your code connects, and injects bounded context so agents stop re-reading files and re-explaining past decisions — even after chat compaction.

It is **not** a Cursor-only product. Cursor is a first-class host and currently the **deepest** path (hooks + PreCompact + distill) because that is where we dogfood hardest. Claude Code, Antigravity, Codex, and generic MCP clients share the same brain; adapter depth follows what each IDE exposes.

It complements the host — it does **not** replace codebase search / Grep, host Memories, or authored rules (`CLAUDE.md`, `.cursor/rules`, `.agents/rules`, …). Storage stays on your machine: `.brain/brain.db` (SQLite).

> **Command flags:** see [CLI_COMMANDS.md](CLI_COMMANDS.md). **Architecture:** see [AI_PROJECT_BRIEF.md](AI_PROJECT_BRIEF.md).

---

## Why it matters for vibe coding

Long agent sessions burn tokens and lose context. Compaction summarizes the chat and drops the decisions you already debated. brainkm fixes that loop across agent IDEs:

- **Stop re-explaining pivots** — “we chose JWT over sessions” lives in the brain, not only in chat history.
- **Stop re-reading whole modules** — get a bounded pack of neighbors + decisions instead of dumping five files.
- **Survive compaction** — PreCompact / synthetic-precompact handover + SessionEnd capture keep truth in SQLite before the window shrinks.
- **Inject only high-signal context** — hard token budget, abstention on weak matches, noise gates so junk stays out.
- **One brain, many hosts** — switch or combine Cursor, Claude, Antigravity, Codex (or another MCP client) without forking project memory.
- **Lightweight local runtime** — shared `brainkm serve` idles ~55–70 MB RAM / ≪1% CPU; active MCP rounds peak ~110 MB ([footprint](benchmarks/2026-07-21-footprint.md)). Optional configure TUI is separate.

---

## Agent tools (MCP)

Six sharp tools the agent (or you) can call. Typed `outputSchema` so clients know the shape of every response.

| Tool | What it does |
|------|----------------|
| **`remember`** | **Pin** durable truth, **correct** a wrong capture (`action=correct` writes a `supersedes` edge), or **archive** noise (`action=archive`). Hooks are the primary capture path. |
| **`recall`** | Search project memory (FTS + graph). Returns `confidence` and optional `decision_trail` (supersede history for why/history questions). Abstains on weak matches. |
| **`context_pack`** | Compile a task pack: decisions + code neighborhood + procedures (+ decision history), under a hard token cap. Auto-queues graph refresh when stale. Prefer before opening 3+ files. |
| **`traverse`** | Impact analysis: AST neighborhood + `impact_summary` (hop counts, high fan-in risk) + linked decision/error neurons. Prefer for blast-radius. |
| **`brain_stats`** | Health snapshot: neuron/graph counts, MCP usage, abstention rate, dead neurons, hygiene hint, compression rollups. Optional per-session breakdown. |
| **`trace_changes`** | File change history: **live** `git log --follow` + uncommitted `git diff`, joined to brain commit↔session↔decision links from `brainkm git-note`. Diffs stay in git (not ingested). |

Graph refresh and session context are automatic (hooks + stale-graph auto-queue). Manual CLI: `brainkm graph sync`, `brainkm hygiene`, `brainkm repair --backfill-links --backfill-supersedes`.

**MCP resources** (read without a tool call):

- **`brainkm://stats`** — brain health JSON
- **`brainkm://neurons`** — active memory titles + ids

---

## Survive long sessions

Hooks wire brainkm into each host’s agent lifecycle so memory keeps working while you vibe. Exact events vary by IDE (see parity table); the jobs are the same:

| Hook | Benefit |
|------|---------|
| **SessionStart** / inject | Migrates the DB and injects a frozen context pack so the agent starts with project memory (hosts that cache prefixes keep that win). Also surfaces a one-shot macOS CLI heal/break notice from `.brain/cli_health.json` when present. |
| **SessionEnd** / idle Stop | Distills the transcript into neurons after you finish — decisions do not die with the tab. |
| **PreCompact** / synthetic precompact | Runs handover *before* the host’s lossy summarize — architectural truth is saved first. |
| **PostCompact** | Refreshes the frozen injection snapshot after compaction so the next turns still see the brain. |
| **PreToolUse** | Injects a bounded `context_pack` before matched write/edit/shell tools — less blind editing. |
| **PostToolUse** | Records capped observations when `capture.auto_observe` is on; requests graph sync after Write/Edit; runs the learning loop (episode-gated co-activation / saturating weights / procedure promotion). |
| **PostToolUseFailure** | Failure observation (hosts that support it). |
| **UserPromptSubmit** | Capped prompt gist observation (where the host supports it). |

### Hook parity (auto-capture)

Shipped adapters below. **Cursor is deepest today** (dogfood); others are first-class and expanding. Any other IDE with MCP can use tools + CLI fallbacks (`handover` / `capture`) even before hooks land.

| Event | Cursor | Claude | Antigravity | Codex | Notes |
|-------|--------|--------|-------------|-------|-------|
| SessionStart injection | yes | yes | via PreInvocation | yes | AGY: ephemeral; Claude/Codex: `hookSpecificOutput` |
| SessionEnd distill + observe promote | yes | yes | idle Stop + debounce | Stop → session-end | Codex has no SessionEnd; AGY Stop writes the **project** `.brain/` (hooks bake `--project-dir`; auto-heal removes shadow `.agents/.brain`) |
| PreCompact handover | yes | yes | synthetic on PreInvocation | yes | AGY has no host PreCompact |
| PostCompact refresh | — | yes | — | yes | Claude + Codex |
| PostToolUse observe | yes | yes | yes (AGY tool names) | yes | Matchers include Bash/apply_patch/MCP |
| UserPromptSubmit | yes | yes | — | yes | Gist only |
| PostToolUseFailure | — | yes | — | — | Cursor: failure on PostToolUse |
| SubagentStart / SubagentStop | — | yes | — | — | Claude: SubagentStart injects frozen pack |
| Stop | — | yes | yes (tiered) | capture | Codex Stop runs `session-end` (JSON `continue`) |

| Host | Hooks / rules | MCP config |
|------|---------------|------------|
| Cursor | `.cursor/hooks.json`, rules | `.cursor/mcp.json` |
| Claude Code | `.claude/settings.json` | project `.mcp.json` |
| Antigravity | `.agents/hooks.json`, `.agents/rules` | `.agents/mcp_config.json` (HTTP: `serverUrl`) |
| Codex CLI | `.codex/hooks.json`, `AGENTS.md`, `.codex/skills/` | `.codex/config.toml` `[mcp_servers.brainkm]` |
| generic | CLI fallbacks | `.brain/mcp.http.example.json` or shared HTTP |

### Distill modes (extractor backends)

`capture.distill_mode` is **one project-wide setting** shared by every connected IDE. It chooses the **extractor**, not the transcript parser (parsing is already per-host).

| Mode | Mechanism | Typical pick |
|------|-----------|--------------|
| `cursor` | Cursor Agent CLI when available; else Cursor-aware heuristics | Cursor dogfood / no cloud |
| `claude` | `claude -p` (+ MCP sampling when live); legacy `mcp` → `claude` | Claude Code local CLI |
| `antigravity` | `agy -p` | Antigravity local CLI |
| `codex` | `codex exec` (read-only, unattended) | Codex CLI |
| `groq` / `ollama` | Shared cloud / local LLM | Same backend for every IDE |
| `rules` | Offline pattern fallback | CI / no LLM |

Prefer a **generic** mode (`groq` or `ollama`) when multiple IDEs share one brain. IDE-named modes are optional when you want that product’s CLI; they still run on any host’s already-parsed rounds.

### Coexistence with host-native memory

| Layer | Role |
|-------|------|
| Host rules / Memories / codebase index | Static policy, cross-project prefs, symbol search (Cursor, Claude, AGY, …) |
| `CLAUDE.md` / Auto Memory | Claude static instructions + private notes — brainkm does not write Auto Memory |
| `.agents/rules` / `AGENTS.md` (Antigravity) | Authored static instructions; grant `mcp(brainkm/*)` |
| `AGENTS.md` / `.codex/` (Codex CLI) | Authored instructions + trusted project hooks; MCP in `config.toml` |
| brainkm (`.brain/brain.db`) | Searchable decisions, Graphify, session/compaction survival — **shared across hosts** |

### Shared localhost brain

**Easiest:** `brainkm configure` → check the apps you use → on Done, click **Start Brain** when sharing across two or more. One app needs no serve step.

Advanced / scripts:

```bash
brainkm serve --project-dir .
brainkm connect cursor --http
brainkm connect claude --http --hooks
brainkm connect antigravity --http --hooks
brainkm connect codex --http --hooks
brainkm doctor
```

One HTTP process + one `.brain/brain.db`. `install --http` (or multi-app wizard) enables `mcp.transport=http` and `capture.auto_observe`.

**Codex notes:** MCP lives in `.codex/config.toml` (not JSON). Trust the project `.codex/` layer, then open `/hooks` in Codex and trust the brainkm commands — untrusted project hooks are skipped. Distill peer: `capture.distill_mode: codex` → `codex exec` (read-only, unattended; rules fallback).

Manual fallbacks when hooks are unavailable: `brainkm handover`, `brainkm capture`.

---

## Remember project truth

| Feature | Benefit |
|---------|---------|
| **Hooks + `auto_observe`** | Primary fill path: SessionEnd distill, capped PostToolUse / prompt / failure observations → promote. Agents do not need to call `remember` every turn. |
| **Neurons** | Project facts, decisions, rules, and known errors — searchable, inspectable rows, not chat sludge. Lifecycle: observation → episode → semantic memory → procedure. |
| **File / symbol links** | `about_file` / `about_symbol` edges attach memories to code nodes; `brainkm file-history` lists them. |
| **Commit trace joins** | New brains default `git.commit_trace=true` (post-commit → `brainkm git-note`). Existing configs that never set the key stay **Off** until enabled in `brainkm configure` → Git (grandfather). Hygiene soft-archives unlinked commit nodes older than `git.commit_retention_days` (default 90). Merges/empty commits are skipped. `trace_changes` / `brainkm trace` always read live git. |
| **Concepts** | Deterministic `kind=concept` nodes from tags/paths/symbols (LLM distill enriches tags only). |
| **Provenance** | `distilled_from` edges + optional MCP `include_sources`; `brainkm provenance <id>`. |
| **Transcript distill** | Session JSONL → chunks → neurons. Chat becomes durable memory instead of a disposable scrollback. |
| **Plan-file ingest** | Pulls `.cursor/plans/*.plan.md` so plan changes become recallable context. |
| **`remember` (pin/correct/archive)** | Explicit durable pin, fix a wrong auto-capture, or archive noise — not the everyday store path. |
| **Supersede / conflict** | New truth can replace old (“we switched off Redis”) instead of stacking contradictory ADD-only facts. |
| **Confidence + review queue** | Low-confidence auto-captures wait for `brainkm review approve` / `reject` (also on the configure Dashboard Review Queue — `y` / `n`) — you gate what the agent trusts. |

---

## Navigate code structure

| Feature | Benefit |
|---------|---------|
| **Graphify AST graph** | Files, classes, functions, and edges in `brain.db` — structural map of *this* project. |
| **`traverse` / `context_pack` neighborhoods** | Answer “what connects to X?” and seed packs from symbols or paths without dumping whole trees. |
| **Auto-sync** | After Write/Edit, the MCP server debounces background extract+import (default on). Graph stays roughly current while you code. |
| **Optional filesystem watch** | Opt-in: changes from any editor (or checkout) request the same sync pipeline — useful for multi-IDE workflows. |
| **`graph sync` / `import` / `extract` / `status`** | Manual control: full refresh, re-import only, extract only, or check staleness and node counts. |

Graphify maps structure; the host’s semantic codebase index still finds symbols by meaning. Use both.

---

## Smart retrieval

| Feature | Benefit |
|---------|---------|
| **FTS5 BM25** | Fast keyword search over neurons — works offline with zero LLM. |
| **Abstention (default P10)** | Low-confidence hits return empty. Silence beats wrong context. |
| **Hybrid RRF + optional MiniLM** | When semantic search is enabled, fuse keyword + vector ranking for better recall on paraphrases. |
| **Weighted PPR graph activation** | Spreads relevance across the code/memory graph so packs include useful neighbors, not random hits. |
| **Intent routing** | Budgets adapt to the kind of question (decision vs navigation vs error) so packs stay on-task. |
| **Summary-first packs** | Lead with gists, then detail — agents get the point before burning tokens. |
| **≤1500 token budget** | Hard cap on agent-facing packs. Predictable cost; no silent multi-file dumps. |
| **Usage feedback ranking** | What the agent actually used gets boosted; unused noise decays over time. |

Optional semantic stack: `pip install -e "./brainkm[semantic]"` + `brainkm semantic doctor` (or TUI consent). Default stays hashing / FTS-first.

---

## Token compression

Content-class pipeline on write and egress (default on via `compression` in `.brain/config.json`). Decisions/rules stay lossless at store; tool logs can use RTK-lite with tee; packs get session dedup + inflation guards under the token budget.

| Feature | Benefit |
|---------|---------|
| **Classify → protect → compress** | Subtype-aware: protect durable truth; trim verbose tool/error surfaces. |
| **Session dedup + inflation guard** | Avoid re-injecting the same neurons; never expand past the budget. |
| **Dual-store / canary** | Sticky engine version per session; rollups on `brain_stats.compression`. |
| **Optional LLMLingua-2** | `pip install -e "./brainkm[compression]"` + `compression.llmlingua_enabled` after fidelity checks (fail-open). |
| **Optional terse-agent skill** | Host skill for professional brevity; not meme caveman-speak. |

Design notes: [research/TOKEN_COMPRESSION.md](research/TOKEN_COMPRESSION.md).

---

## Capture quality

| Feature | Benefit |
|---------|---------|
| **Distill mode: `rules`** | Zero-dependency default. Offline extract with no API key — always works. |
| **Distill mode: `cursor` / `claude` / `antigravity` / `codex`** | Host-peer distill (`agent` / `claude -p` / `agy -p` / `codex exec`) when that CLI is available. |
| **Distill mode: `ollama`** | Local LLM distill on your machine — private, no cloud. |
| **Distill mode: `groq`** | Fast cloud distill when you want quality without a local GPU (`GROQ_API_KEY` in env only). |
| **Distill mode: `mcp`** (legacy → `claude`) | Host MCP sampling when the client supports it. |
| **Chrome cleaning** | Strips host UI / tool chrome before extract so neurons are not full of noise. |
| **Injection noise gate** | Packs re-filter junk at injection time — distilled trash stays out of the agent window. |
| **Doctors** | `ollama` / `groq` / `cursor` / `semantic doctor` — readiness checks before you rely on a mode. `brainkm doctor` also warns on macOS UF_HIDDEN `.pth` / broken CLI breadcrumbs. |

---

## Keep the brain clean

| Feature | Benefit |
|---------|---------|
| **`hygiene`** | Soft-archives noisy or unused neurons so packs stay sharp. Safe to re-run (`--dry-run` available). |
| **`consolidate` / decay** | Merges near-duplicates and decays stale unused memory — sleep-time cleanup. |
| **Soft archive + audit** | `remember action=archive` (or CLI forget path) with an audit trail; no silent hard deletes on the agent path. |
| **`repair`** | Rebuilds FTS5, re-scans for leaked secrets, runs integrity checks when the DB feels wrong. |
| **Review approve / reject** | Human-in-the-loop for pending auto-captures. |

---

## Setup & clients

| Feature | Benefit |
|---------|---------|
| **`brainkm configure` TUI** | **Recommended setup:** pick coding apps (checkboxes), Semantic Quality consent, Start Brain for shared mode, live status (incl. MCP Doctor), validated config edits. |
| **`brainkm install`** | Scaffolds `.brain/`, MCP config, hooks, and rules for **Cursor**, **Claude Code**, **Antigravity**, **Codex**, or **generic** MCP hosts (`--http` for shared). Per-host exclusivity: [install/](install/). |
| **`serve` / `connect` / `doctor`** | Shared HTTP brain wiring and health checks (TUI Start/Stop/**Restart** wraps serve) — one brain for every connected IDE. Doctor also flags macOS CLI import heal/break breadcrumbs. Dashboard shows package vs serve version and warns on mismatch. |
| **macOS CLI auto-heal** | Launcher clears `UF_HIDDEN` on `.venv` `*.pth`, writes `.brain/cli_health.json`; SessionStart injects a one-shot notice. Hard fix: `bash brainkm/scripts/repair_venv.sh`. |
| **`migrate`** | Applies pending SQLite migrations when the package advances. |
| **Multi-root config** | Point `project_roots` at monorepo packages so one brain spans related trees. |

> Public one-command install (`uvx` / PyPI / MCP Registry) is deferred until the repo is public and the installable package name is finalized. Local path: [INSTALL.md](INSTALL.md) · per-host: [install/](install/). License: Apache-2.0.

---

## Share & inspect

| Feature | Benefit |
|---------|---------|
| **`export`** | Markdown dump of neurons under `.brain/exports/` — readable, greppable, backup-friendly. |
| **`import`** | Merge or `--replace` neurons from JSON — move brains between machines or reset cleanly. |
| **`team-export` / `team-import`** | Curated high-confidence neurons for shared project conventions (confidence-aware merge). |
| **`viz`** | 3D neuron graph in the browser — opens with a per-run access token; APIs require `?token=` (HttpOnly cookie). |
| **Inspectable SQLite** | Every memory is a row you can query, export, or forget. No black-box cloud store. |

---

## Security & privacy

| Feature | Benefit |
|---------|---------|
| **Local-first SQLite** | Project brain stays under `.brain/` on disk — default path never phones home. |
| **Redaction + injection scan** | Secrets and prompt-injection patterns are blocked or stripped on write *and* before pack injection. |
| **No secrets in neurons / config** | API keys live in env / `.env` only — never in `.brain/config.json` or memory bodies. |
| **HTTP MCP Bearer + loopback** | `serve` / `mcp --http` binds `127.0.0.1` by default; `/mcp` requires Bearer from `.brain/mcp_http_token`; non-loopback needs `--allow-remote`. |
| **Groq cloud consent** | `capture.cloud_distill_acknowledged` required before Groq uploads transcripts (wizard sets it). |
| **Graphify harden** | `extract_extra_args` allowlisted; code-graph import skips redaction-blocked nodes. |
| **`connect` / `doctor`** | Wire any supported host to stdio or shared URL (`serverUrl` for AGY HTTP); detect dual writers, auto_observe, missing Bearer. |

Details: [SECURITY.md](SECURITY.md).

---

## Measure & tune

| Feature | Benefit |
|---------|---------|
| **`bench run`** | **`eval`** runs product-grade suites (retrieval IR metrics, task success, latency smoke/loaded) plus regression canaries. **`cma`** is the public Common Memory Axes scorecard (abilities + tokens + latency). Also: `retrieval`, `task`, `compare` (token proxy), `scorecard`, `longmemeval` (optional footnote), and legacy canaries. |
| **`bench probe`** | Live `context_pack` size for one query vs a naive multi-file baseline. |
| **Abstention calibrate** | Tune recall thresholds from fixtures so silence vs noise matches your corpus. |

Headline targets (see [BENCHMARKS.md](BENCHMARKS.md)): **`bench run cma`** for public agentic-memory comparison (ability accuracy + ≤1500 pack tokens + latency); **`bench run eval`** for product IR/task/latency gates. `compare` remains a token-savings proxy only.

---

## When to use what

| Question | Use first |
|----------|-----------|
| Where is symbol X defined? | Host codebase index / Grep |
| Why did we choose X over Y? | **brainkm `recall`** |
| What calls / imports X? Impact of changing Y? | **`traverse`** (symbol/path) |
| What changed in this file recently, and why? | **`trace_changes`** (path) — live git + brain joins |
| Understand one module (would open 3+ files) | **`context_pack`**, then verify in source |
| Cross-project personal prefs | Host Memories (not brainkm) |
| Static team policy | Host rules files — brainkm stores *learned* project context |
| Pin a decision / correct bad auto-memory | MCP **`remember`** (hooks fill ordinary learning) |

Always verify packs in source before editing. Empty or wrong graph? Check `brain_stats` / `graph status` — stale graphs auto-queue a refresh, or run `brainkm graph sync`.

---

## Quick start

Clone-local setup and MCP wiring:

→ **[INSTALL.md](INSTALL.md)** · **[install/](install/)** (per host) · **[README.md](../README.md)**

```bash
bash brainkm/scripts/setup_dev.sh
source .venv/bin/activate
pip install -e "./brainkm[tui]"
brainkm configure   # recommended: pick the IDEs you use
# or: brainkm install --dev --client cursor|claude|antigravity|codex|generic
brainkm version
```
