# MemNetwork (brainkm)

This project uses **brainkm** — a local SQLite project brain at `.brain/brain.db`.

## Before reading many files

- Prefer MCP **`traverse`** for call/import/flow and blast-radius questions ("what calls X?",
  "what breaks if I change Y?") — pass a symbol or path; then confirm with targeted reads.
- Prefer MCP **`context_pack`** for multi-file task context (include a **symbol or file path**
  in the query or `seed_refs`), **then verify in source** before editing — packs are hints,
  never a substitute for reading the code you will change.
- Use **`recall`** for architectural decisions, rules, and past pivots — not chat history alone.
- Memory is filled primarily by **hooks** (SessionEnd distill, PostToolUse observations,
  SessionStart injection). Call **`remember` only to pin** durable project truth or **correct**
  a wrong auto-capture — not for ordinary session learning.

## Tool routing (locate vs flow vs decisions)

| Question type | Use first | Why |
|---------------|-----------|-----|
| "Where is symbol X defined?" | Grep / project search | Semantic/symbol locate |
| "What calls / imports X?" / "impact of changing Y" | **`traverse`** (symbol/path), then verify | Focused AST neighborhood |
| "Why did we choose X?" | **`recall`** | Decisions live in neurons, not the code index |
| Understand one module (would open 3+ files) | **`context_pack`** then targeted reads | Bounded pack vs file dumps |

Do **not** treat brainkm as a second project search index. Use Grep/search to **locate**; use
Graphify (`traverse` for flow, `context_pack` for task packs) to explain structure. Never skip
reading source because a pack abstained or looked incomplete — prefer fewer injected tokens over
trusting noise.

If `traverse` / `context_pack` results look empty or wrong, check **`brain_stats`** first —
a stale or missing code graph is the usual cause; refresh with **`graph_sync`** (or
`brainkm graph sync`) instead of distrusting the whole brain. Empty `traverse` responses
include a `hint` and `resolved_id` when the graph matched but had no neighbors.

## What lives in the brain

| Store | Contents |
|-------|----------|
| Neurons (`memory`) | Decisions, rules, facts, errors, context |
| Code graph (`code`) | Graphify AST nodes — files, classes, functions, edges |
| Session chunks | Raw transcript search index (distilled into neurons) |

## Coexistence with Claude native memory

- **CLAUDE.md / `.claude/rules`** = authored project instructions (static).
- **Claude Auto Memory (`MEMORY.md`)** = Claude's private notes — leave alone; do not rewrite.
- **brainkm** = searchable project decisions, code graph, and compaction survival.
- Shared with Cursor / Antigravity: one `brainkm serve` + `connect --http` (AGY MCP field is `serverUrl`).

Prefs and debug insights stay in Auto Memory. Durable team architecture → brainkm.

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
