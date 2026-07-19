# MemNetwork (brainkm)

This project uses **brainkm** — a local SQLite project brain at `.brain/brain.db`.

## Before reading many files

- Prefer MCP **`traverse`** for call/import/flow and blast-radius questions — pass a symbol or path; then confirm with targeted reads.
- Prefer MCP **`context_pack`** for multi-file task context (include a **symbol or file path**), **then verify in source** before editing.
- Use **`recall`** for architectural decisions, rules, and past pivots.
- Memory accumulates from **hooks** (PreInvocation inject, Stop distill, PostToolUse observations). Call **`remember` only to pin** durable project truth or **correct** a wrong auto-capture.

## Tool routing

| Question type | Use first |
|---------------|-----------|
| "Where is symbol X defined?" | Grep / project search |
| "What calls / imports X?" | **`traverse`**, then verify |
| "Why did we choose X?" | **`recall`** |
| Understand one module (3+ files) | **`context_pack`** then targeted reads |

## Permissions

Grant **`mcp(brainkm/*)`** (or always-allow brainkm tools) so recall/context_pack are not stuck in Ask mode.

## Coexistence

- **`.agents/rules` / `AGENTS.md`** = authored static instructions.
- **brainkm** = searchable project decisions, code graph, session survival.
- Do **not** stack Mem0 (or similar memory MCP) with brainkm on the same project.

## Lifecycle (Antigravity)

- **PreInvocation** injects a throttled frozen pack (`injectSteps.ephemeralMessage`).
- **Stop** (when fully idle) distills the transcript; synthetic precompact also runs on long PreInvocation turns.
- HTTP shared brain uses **`serverUrl`** in `.agents/mcp_config.json` (not `url`).
- Distill: `capture.distill_mode: antigravity` (`agy -p`) when the CLI is installed.
- Manual fallback: `brainkm handover`, `brainkm capture`.
