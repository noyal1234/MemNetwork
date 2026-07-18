# brainkm — Features

**brainkm** is a local, project-scoped brain for coding agents. It remembers *why* you chose something, maps how your code connects, and injects bounded context so agents stop re-reading files and re-explaining past decisions — even after Cursor chat compaction.

It complements Cursor — it does **not** replace `@codebase`, Cursor Memories, or static rules. Storage stays on your machine: `.brain/brain.db` (SQLite).

> **Command flags:** see [CLI_COMMANDS.md](CLI_COMMANDS.md). **Architecture:** see [AI_PROJECT_BRIEF.md](AI_PROJECT_BRIEF.md).

---

## Why it matters for vibe coding

Long agent sessions burn tokens and lose context. Compaction summarizes the chat and drops the decisions you already debated. brainkm fixes that loop:

- **Stop re-explaining pivots** — “we chose JWT over sessions” lives in the brain, not only in chat history.
- **Stop re-reading whole modules** — get a bounded pack of neighbors + decisions instead of dumping five files.
- **Survive compaction** — PreCompact handover + SessionEnd capture keep truth in SQLite before the window shrinks.
- **Inject only high-signal context** — hard token budget, abstention on weak matches, noise gates so junk stays out.

---

## Agent tools (MCP)

Eight tools the agent (or you) can call. Typed `outputSchema` so clients know the shape of every response.

| Tool | What it does |
|------|----------------|
| **`remember`** | **Pin** durable project truth or **correct** a wrong auto-capture. Hooks are the primary capture path — do not rely on the agent calling this for ordinary learning. |
| **`recall`** | Search project memory (FTS + graph). Returns nothing when confidence is too low — so weak noise does not pollute the chat. |
| **`context_pack`** | Compile a task pack: relevant neurons + code neighborhood + procedures, under a hard token cap. Prefer before opening 3+ files (not for pure blast-radius — use `traverse`). |
| **`traverse`** | Focused AST neighborhood for one symbol/path: callers, callees, imports. Prefer for blast-radius; defaults to `direction=both` and structural edges. |
| **`session_status`** | Read or write the current session’s context neuron — keep “what we’re doing now” durable mid-session. |
| **`forget`** | Soft-archive a neuron (reversible). Wrong or stale memories leave without a hard delete. |
| **`brain_stats`** | Health snapshot: neuron/graph counts, MCP usage, abstention rate, dead neurons. Optional per-session breakdown. |
| **`graph_sync`** | Queue or force a code-graph refresh (Graphify extract + import) when the structure feels stale. |

**MCP resources** (read without a tool call):

- **`brainkm://stats`** — brain health JSON
- **`brainkm://neurons`** — active memory titles + ids

---

## Survive long sessions

Hooks wire brainkm into the agent lifecycle so memory keeps working while you vibe:

| Hook | Benefit |
|------|---------|
| **SessionStart** | Migrates the DB and injects a frozen context pack so the agent starts with project memory (and Cursor can cache the prefix). |
| **SessionEnd** | Distills the transcript into neurons after you finish — decisions do not die with the tab. |
| **PreCompact** | Runs handover *before* Cursor’s lossy summarize — architectural truth is saved first. |
| **PostCompact** | Refreshes the frozen injection snapshot after compaction so the next turns still see the brain. |
| **PreToolUse** | Injects a bounded `context_pack` before matched write/edit/shell tools — less blind editing. |
| **PostToolUse** | Records capped observations when `capture.auto_observe` is on; requests graph sync after Write/Edit; runs the learning loop (co-activation / procedures). |
| **PostToolUseFailure** | Failure observation (Claude / hosts that support it). |
| **UserPromptSubmit** | Capped prompt gist observation (where the host supports it). |

### Hook parity (auto-capture)

| Event | Cursor | Claude | Codex | Notes |
|-------|--------|--------|-------|-------|
| SessionStart injection | yes | yes | yes | Frozen pack; Claude uses `hookSpecificOutput` |
| SessionEnd distill + observe promote | yes | yes | yes | Primary memory path |
| PreCompact handover | yes | yes | yes | |
| PostCompact refresh | — | yes | — | Claude-only; refreshes frozen pack |
| PostToolUse observe | yes | yes | yes | Claude install enables `auto_observe` by default |
| UserPromptSubmit | yes | yes | — | Gist only |
| PostToolUseFailure | — | yes | — | Cursor: failure payload on PostToolUse |
| SubagentStart / SubagentStop | — | yes | — | Multi-agent silent path |
| Stop | — | yes | — | Flush use counts / optional gist |

Claude hooks install into **`.claude/settings.json`** (not `.claude/hooks.json`). MCP is project **`.mcp.json`**.

### Coexistence with Claude native memory

| Layer | Role |
|-------|------|
| `CLAUDE.md` / `.claude/rules` | Authored static instructions |
| Claude Auto Memory (`MEMORY.md`) | Claude's private notes — brainkm does not write here |
| brainkm (`.brain/brain.db`) | Searchable decisions, Graphify, compaction survival |

### Shared localhost brain

**Easiest:** `brainkm configure` → check the apps you use → on Done, click **Start Brain** when sharing across two or more. One app needs no serve step.

Advanced / scripts:

```bash
brainkm serve --project-dir .
brainkm connect cursor --http
brainkm connect claude --http --hooks
brainkm connect codex --http
brainkm doctor
```

One HTTP process + one `.brain/brain.db`. `install --http` (or multi-app wizard) enables `mcp.transport=http` and `capture.auto_observe`.

Manual fallbacks when hooks are unavailable: `brainkm handover`, `brainkm capture`.

---

## Remember project truth

| Feature | Benefit |
|---------|---------|
| **Hooks + `auto_observe`** | Primary fill path: SessionEnd distill, capped PostToolUse / prompt / failure observations → promote. Agents do not need to call `remember` every turn. |
| **Neurons** | Project facts, decisions, rules, and known errors — searchable, inspectable rows, not chat sludge. Lifecycle: observation → episode → semantic memory → procedure. |
| **File / symbol links** | `about_file` / `about_symbol` edges attach memories to code nodes; `brainkm file-history` lists them. |
| **Concepts** | Deterministic `kind=concept` nodes from tags/paths/symbols (LLM distill enriches tags only). |
| **Provenance** | `distilled_from` edges + optional MCP `include_sources`; `brainkm provenance <id>`. |
| **Transcript distill** | Session JSONL → chunks → neurons. Chat becomes durable memory instead of a disposable scrollback. |
| **Plan-file ingest** | Pulls `.cursor/plans/*.plan.md` so plan changes become recallable context. |
| **`remember` (pin/correct)** | Explicit durable pin or fix a wrong auto-capture — not the everyday store path. |
| **Supersede / conflict** | New truth can replace old (“we switched off Redis”) instead of stacking contradictory ADD-only facts. |
| **Confidence + review queue** | Low-confidence auto-captures wait for `brainkm review approve` / `reject` — you gate what the agent trusts. |

---

## Navigate code structure

| Feature | Benefit |
|---------|---------|
| **Graphify AST graph** | Files, classes, functions, and edges in `brain.db` — structural map of *this* project. |
| **`traverse` / `context_pack` neighborhoods** | Answer “what connects to X?” and seed packs from symbols or paths without dumping whole trees. |
| **Auto-sync** | After Write/Edit, the MCP server debounces background extract+import (default on). Graph stays roughly current while you code. |
| **Optional filesystem watch** | Opt-in: changes from any editor (or checkout) request the same sync pipeline — useful for multi-IDE workflows. |
| **`graph sync` / `import` / `extract` / `status`** | Manual control: full refresh, re-import only, extract only, or check staleness and node counts. |

Graphify maps structure; Cursor `@codebase` still finds symbols by meaning. Use both.

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

## Capture quality

| Feature | Benefit |
|---------|---------|
| **Distill mode: `rules`** | Zero-dependency default. Offline extract with no API key — always works. |
| **Distill mode: `cursor`** | Uses Cursor-aware distill (agent CLI when available) for higher-quality session capture. |
| **Distill mode: `ollama`** | Local LLM distill on your machine — private, no cloud. |
| **Distill mode: `groq`** | Fast cloud distill when you want quality without a local GPU (`GROQ_API_KEY` in env only). |
| **Distill mode: `mcp`** | Uses the host’s MCP sampling API when the client supports it. |
| **Chrome cleaning** | Strips Cursor UI chrome before extract so neurons are not full of tool noise. |
| **Injection noise gate** | Packs re-filter junk at injection time — distilled trash stays out of the agent window. |
| **Doctors** | `ollama` / `groq` / `cursor` / `semantic doctor` — readiness checks before you rely on a mode. |

---

## Keep the brain clean

| Feature | Benefit |
|---------|---------|
| **`hygiene`** | Soft-archives noisy or unused neurons so packs stay sharp. Safe to re-run (`--dry-run` available). |
| **`consolidate` / decay** | Merges near-duplicates and decays stale unused memory — sleep-time cleanup. |
| **Soft `forget` + audit** | Archives with an audit trail; no silent hard deletes on the agent path. |
| **`repair`** | Rebuilds FTS5, re-scans for leaked secrets, runs integrity checks when the DB feels wrong. |
| **Review approve / reject** | Human-in-the-loop for pending auto-captures. |

---

## Setup & clients

| Feature | Benefit |
|---------|---------|
| **`brainkm configure` TUI** | **Recommended setup:** pick coding apps (checkboxes), Semantic Quality consent, Start Brain for shared mode, live status, validated config edits. |
| **`brainkm install`** | Scaffolds `.brain/`, MCP config, hooks, and rules for **Cursor**, **Claude Code**, **Codex**, or **generic** MCP clients (`--http` for shared). |
| **`serve` / `connect` / `doctor`** | Shared HTTP brain wiring and health checks (TUI Start/Stop wraps serve). |
| **`migrate`** | Applies pending SQLite migrations when the package advances. |
| **Multi-root config** | Point `project_roots` at monorepo packages so one brain spans related trees. |

> Public one-command install (`uvx` / PyPI / MCP Registry) is deferred while the repo is private. Local path: [INSTALL.md](INSTALL.md).

---

## Share & inspect

| Feature | Benefit |
|---------|---------|
| **`export`** | Markdown dump of neurons under `.brain/exports/` — readable, greppable, backup-friendly. |
| **`import`** | Merge or `--replace` neurons from JSON — move brains between machines or reset cleanly. |
| **`team-export` / `team-import`** | Curated high-confidence neurons for shared project conventions (confidence-aware merge). |
| **`viz`** | 3D neuron graph in the browser — see how memories connect. |
| **Inspectable SQLite** | Every memory is a row you can query, export, or forget. No black-box cloud store. |

---

## Security & privacy

| Feature | Benefit |
|---------|---------|
| **Local-first SQLite** | Project brain stays under `.brain/` on disk — default path never phones home. |
| **Redaction + injection scan** | Secrets and prompt-injection patterns are blocked or stripped on write *and* before pack injection. |
| **No secrets in neurons / config** | API keys live in env / `.env` only — never in `.brain/config.json` or memory bodies. |
| **HTTP MCP on localhost** | `brainkm serve` / `mcp --http` binds to `127.0.0.1` by default; `/health` for doctor. |
| **`connect` / `doctor`** | Wire Cursor / Claude / Codex to stdio or shared URL; detect dual writers + auto_observe. |

Details: [SECURITY.md](SECURITY.md).

---

## Measure & tune

| Feature | Benefit |
|---------|---------|
| **`bench run`** | **`eval`** runs product-grade suites (retrieval IR metrics, task success, latency smoke/loaded) plus regression canaries. Also: `retrieval`, `task`, `compare` (token proxy), and legacy canaries. |
| **`bench probe`** | Live `context_pack` size for one query vs a naive multi-file baseline. |
| **Abstention calibrate** | Tune recall thresholds from fixtures so silence vs noise matches your corpus. |

Headline targets (see [BENCHMARKS.md](BENCHMARKS.md)): **`bench run eval`** reports Recall@5 ~0.98, task gold coverage **with 97% / selective-without 83%**, and loaded latency p95 within corpus-scaled SLOs. `compare` remains a token-savings proxy only.

---

## When to use what

| Question | Use first |
|----------|-----------|
| Where is symbol X defined? | Cursor `@codebase` / Grep |
| Why did we choose X over Y? | **brainkm `recall`** |
| What calls / imports X? Impact of changing Y? | **`traverse`** (symbol/path) |
| Understand one module (would open 3+ files) | **`context_pack`**, then verify in source |
| Cross-project personal prefs | Cursor Memories (not brainkm) |
| Static team policy | `.cursor/rules/` — brainkm stores *learned* project context |
| Pin a decision / correct bad auto-memory | MCP **`remember`** (hooks fill ordinary learning) |

Always verify packs in source before editing. Empty or wrong graph? Check `brain_stats` / `graph status`, then `graph_sync`.

---

## Quick start

Clone-local setup and MCP wiring:

→ **[INSTALL.md](INSTALL.md)** · **[README.md](../README.md)**

```bash
bash brainkm/scripts/setup_dev.sh
source .venv/bin/activate
pip install -e "./brainkm[tui]"
brainkm configure   # recommended
# or: brainkm install --dev --client cursor
brainkm version
```
