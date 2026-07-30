# MemNetwork (brainkm)

This project uses **brainkm** — a local SQLite project brain at `.brain/brain.db`.

## MUST (Claude Code)

1. Blast-radius / call/import flow: you **MUST** call `traverse` — never text search alone.
2. Decisions / "why X": you **MUST** call `recall`. The SessionStart pack is a hint only —
   it never substitutes for the live call, even if it looks like it already answers the question.
3. Before opening 3+ files for one task: you **MUST** call `context_pack`, then verify in source.
4. "What changed in this file and why": you **MUST** call `trace_changes`.
5. SessionStart injects a **FROZEN** snapshot that does **NOT** update. You **MUST** still call
   live `recall` / `traverse` / `context_pack` / `trace_changes` when the question matches —
   the snapshot is **NOT** a substitute. Tools are deferred: call `ToolSearch` **once** at the
   start of the session (not per-tool) to load all eight brainkm schemas, then call them directly
   for the rest of the session.
6. Pass **`session_id`** (from SessionStart / UserPromptSubmit) on every brainkm call.
7. **Symptom before forensics.** On any error, traceback, or "X isn't working / isn't firing /
   went silent", you **MUST** call `recall` with the raw error or symptom text *before* manual
   debugging. Recurring environment breakage (venv, hooks, MCP wiring) is usually already in
   memory; rediscovering it by hand is the most expensive way to be right. A reproducible stack
   trace is **not** a reason to skip this — it is the highest-signal query you can send.
8. **Pin what you solved.** After diagnosing a non-obvious failure, call `remember`
   (`subtype=error`) with the symptom, the cause, and the fix. Hooks capture transcripts, but a
   raw chunk ranks far below a real neuron — an undocumented fix will be rediscovered.

**Bypass is narrow, not a default.** The only case where skipping brainkm is correct: a pure
mechanical edit (typo fix, rename, formatting) with zero judgment calls — nothing that requires
knowing *why* code is the way it is, *what* it affects, or *how it changed*. If the task touches
more than one file, changes behavior, or you're about to explain a design choice, that is not
this case — call the tool. When in doubt, call it; an unnecessary call costs a few hundred
tokens, a skipped one costs the whole point of having a project brain.

**Counter-rule:** Grep/search is for **locate** only. Finding a file does **NOT** replace
`recall` / `traverse` / `context_pack` for decisions, blast-radius, or multi-file context.

## Before reading many files

- Prefer MCP **`traverse`** for call/import/flow and blast-radius questions ("what calls X?",
  "what breaks if I change Y?") — pass a symbol or path; then confirm with targeted reads.
- Prefer MCP **`trace_changes`** for "what changed in this file recently and why?" — live
  git log joined to commit↔session↔decision links (diffs stay in git).
- Prefer MCP **`context_pack`** for multi-file task context (include a **symbol or file path**
  in the query or `seed_refs`), **then verify in source** before editing — packs are hints,
  never a substitute for reading the code you will change.
- Use **`recall`** for architectural decisions, rules, and past pivots — not chat history alone.
- Memory is filled primarily by **hooks** (SessionEnd distill, PostToolUse observations,
  SessionStart injection). Call **`remember` only to pin** durable project truth or **correct**
  a wrong auto-capture — not for ordinary session learning.
- Omitting `session_id` buckets usage under a shared `__anon__` session and breaks per-session
  `brain_stats` and procedure learning.

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

## Coexistence with Claude native memory

| What to remember | Where it goes | Why |
|------------------|---------------|-----|
| Personal prefs / debug insights | Claude Auto Memory | Per-user, not project-shared |
| Project architecture decisions | brainkm (`recall`) | Survives compaction; shared with Cursor/AGY |
| Team coding conventions | `CLAUDE.md` / `.claude/rules` | Static, versioned policy |
| Durable corrections to wrong captures | brainkm `remember` `action=correct` | Writes supersedes edge |

- **CLAUDE.md / `.claude/rules`** = authored project instructions (static).
- **Claude Auto Memory (`MEMORY.md`)** = Claude's private notes — leave alone; do not rewrite.
- **brainkm** = searchable project decisions, code graph, and compaction survival.
- Shared with Cursor / Antigravity: one `brainkm serve` + `connect --http` (AGY MCP field is `serverUrl`).

## Compaction

- **PreCompact** runs `brainkm handover` before lossy summarize.
- **PostCompact** refreshes the frozen injection snapshot.
- **SessionEnd** captures the transcript into neurons.
- **SubagentStart** injects a frozen pack into Claude subagents.

## Distill

Prefer `capture.distill_mode: claude` (`claude -p`, or live MCP sampling when available). Install with `brainkm install --client claude`.

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
