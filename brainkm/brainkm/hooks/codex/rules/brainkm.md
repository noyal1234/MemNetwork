# MemNetwork (brainkm)

This project uses **brainkm** — a local SQLite project brain at `.brain/brain.db`.

## Before reading many files

- Prefer MCP **`traverse`** for call/import/flow and blast-radius questions ("what calls X?",
  "what breaks if I change Y?") — pass a symbol or path; then confirm with targeted reads.
- Prefer MCP **`trace_changes`** for "what changed in this file recently and why?" — live
  git log joined to commit↔session↔decision links (diffs stay in git).
- Prefer MCP **`context_pack`** for multi-file task context (include a **symbol or file path**
  in the query or `seed_refs`), **then verify in source** before editing — packs are hints,
  never a substitute for reading the code you will change.
- Use **`recall`** for architectural decisions, rules, and past pivots — not chat history alone.
- Memory is filled primarily by **hooks** (Stop distill, PostToolUse observations,
  SessionStart injection). Call **`remember` only to pin** durable project truth or **correct**
  a wrong auto-capture — not for ordinary session learning.

## Tool routing (locate vs flow vs decisions)

| Question type | Use first | Why |
|---------------|-----------|-----|
| "Where is symbol X defined?" | Grep / project search | Semantic/symbol locate |
| "What calls / imports X?" / "impact of changing Y" | **`traverse`** (symbol/path), then verify | Focused AST neighborhood |
| "What changed in file Y recently / why?" | **`trace_changes`** (path) | Live git timeline + commit joins |
| "Why did we choose X?" | **`recall`** | Decisions live in neurons, not the code index |
| Understand one module (would open 3+ files) | **`context_pack`** then targeted reads | Bounded pack vs file dumps |

Do **not** treat brainkm as a second project search index. Use Grep/search to **locate**; use
Graphify (`traverse` for flow, `context_pack` for task packs) to explain structure. Never skip
reading source because a pack abstained or looked incomplete — prefer fewer injected tokens over
trusting noise.

If `traverse` / `context_pack` results look empty or wrong, check **`brain_stats`** first —
a stale or missing code graph is the usual cause; reads auto-queue a refresh, or run
`brainkm graph sync`. Empty `traverse` responses include a `hint`, `resolved_id`, and
`impact_summary` when the graph matched but had no neighbors.

### Diagnose mode (something is broken)

The rows above are **build mode** — planning a change. When something is *failing*, the same
tools answer different questions, and the trigger is the **symptom**, not a decision:

| Symptom-side question | Use first | Why |
|-----------------------|-----------|-----|
| Any error text, traceback, or exception | **`recall`** with the raw error string | Past occurrences and their fixes are neurons — query the error *before* hand-debugging |
| "X is silent / not firing / stopped working" | **`recall`** (symptom phrasing routes to DEBUG intent) | DEBUG boosts `error` neurons; "why" phrasing alone boosts decisions and buries them |
| "This worked before — what broke it?" | **`trace_changes`** (path) | Regression bisect against the live commit timeline |
| "What could reach this failing symbol?" | **`traverse`** (`direction=in`) | Callers/producers of the bad state, not just blast radius |
| Debugging that spans 3+ files | **`context_pack`** | The 3-file rule applies to diagnosis, not only to editing |
| You just solved a non-obvious failure | **`remember`** (`subtype=error`) | Otherwise the fix survives only as a raw transcript chunk and will not rank for the next person |

**Order matters.** A reproducible stack trace feels more authoritative than memory, so the
instinct is to start hand-debugging immediately. Call `recall` first — it is one call, and an
error string is the highest-signal query this brain can receive. Recurring environment
breakage (venv, hooks, MCP wiring) is exactly the class that is already in memory and gets
rediscovered the hard way.

## What lives in the brain

| Store | Contents |
|-------|----------|
| Neurons (`memory`) | Decisions, rules, facts, errors, context |
| Code graph (`code`) | Graphify AST nodes — files, classes, functions, edges |
| Session chunks | Raw transcript search index (distilled into neurons) |

## Coexistence with Codex

- **`AGENTS.md` / project instructions** = authored static policy.
- **brainkm** = searchable project decisions, code graph, and compaction survival.
- Trust this project's `.codex/` layer, then open **`/hooks`** in Codex and trust the brainkm hooks
  (Codex skips untrusted project hooks).
- Shared with Cursor / Claude / Antigravity: one `brainkm serve` + `connect --http`.

## Compaction

- **PreCompact** runs `brainkm handover` before lossy summarize.
- **PostCompact** refreshes the frozen injection snapshot.
- **Stop** captures the transcript into neurons (Codex has no SessionEnd).

## Distill

Prefer `capture.distill_mode: codex` (`codex exec`) when the Codex CLI is installed.
Install with `brainkm install --client codex`.

## Manual fallback (hooks unavailable)

```bash
brainkm handover path/to/transcript.jsonl   # before compact
brainkm capture path/to/transcript.jsonl      # after session
brainkm graph sync                            # refresh code graph (extract + import)
brainkm graph sync --skip-extract             # import existing graph.json only
brainkm hygiene                               # soft-archive noisy auto-captured neurons
```

Auto-sync runs in the MCP server after Write/Edit (debounced). Disable via `.brain/config.json`:
`"graphify": { "auto_sync": { "enabled": false } }`.
