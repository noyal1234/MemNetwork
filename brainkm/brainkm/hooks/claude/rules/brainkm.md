# MemNetwork (brainkm)

This project uses **brainkm** — a local SQLite project brain at `.brain/brain.db`.

## Before reading many files

- Prefer MCP **`traverse`** for call/import/flow and blast-radius questions — pass a symbol or path; then confirm with targeted reads.
- Prefer MCP **`context_pack`** for multi-file task context (include a **symbol or file path**), **then verify in source** before editing.
- Use **`recall`** for architectural decisions, rules, and past pivots.
- Memory is filled primarily by **hooks** (SessionEnd distill, PostToolUse observations, SessionStart injection). Call **`remember` only to pin** durable project truth or **correct** a wrong auto-capture.

## Tool routing

| Question type | Use first |
|---------------|-----------|
| "Where is symbol X defined?" | Grep / project search |
| "What calls / imports X?" | **`traverse`**, then verify |
| "Why did we choose X?" | **`recall`** |
| Understand one module (3+ files) | **`context_pack`** then targeted reads |

## Coexistence with Claude native memory

- **CLAUDE.md / `.claude/rules`** = authored project instructions (static).
- **Claude Auto Memory (`MEMORY.md`)** = Claude's private notes — leave alone; do not rewrite.
- **brainkm** = searchable project decisions, code graph, and compaction survival.

Prefs and debug insights stay in Auto Memory. Durable team architecture → brainkm.

## Compaction

- **PreCompact** runs `brainkm handover` before lossy summarize.
- **PostCompact** refreshes the frozen injection snapshot.
- **SessionEnd** captures the transcript into neurons.

## Distill

Prefer `capture.distill_mode: claude` (`claude -p`, or live MCP sampling when available). Install with `brainkm install --client claude`.
