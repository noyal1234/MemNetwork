---
name: brainkm-routing
description: >-
  When to use brainkm MCP tools (recall, context_pack, traverse, trace_changes) vs
  Grep/project search. Prefer file-seeded recall and verify packs in source.
  Install with brainkm install.
---

# brainkm tool routing

brainkm is this project's brain (`.brain/brain.db`). It complements Grep and project
search — it does not replace them.

## Use first

| Question | Tool |
|----------|------|
| Why did we choose X? Past decision / pivot | `recall` (uses `decision_trail`) |
| What calls / imports X? Blast radius / impact | `traverse` (`impact_summary` + linked neurons) |
| What changed in this file recently and why? | `trace_changes` (live git + commit joins) |
| Understand a module before editing 3+ files | `context_pack` (include path or symbol) |
| What did we learn about `auth.ts`? | `recall` / `context_pack` with that path in the query |
| Pin, correct, or archive durable truth | `remember` (`action=pin\|correct\|archive`; hooks are primary capture) |

## MUST (Claude Code)

1. Blast-radius / call/import flow: you **MUST** call `traverse` — never text search alone.
2. Decisions / "why X": you **MUST** call `recall` unless the SessionStart pack already answers
   that **exact** question.
3. Before opening 3+ files for one task: you **MUST** call `context_pack`, then verify in source.
4. "What changed in this file and why": you **MUST** call `trace_changes`.
5. SessionStart pack is frozen — if insufficient, you **MUST** still call the live tool.
   Load via `ToolSearch` first if tools are deferred; pass `session_id` on every call.

**Bypass:** single-file typo/rename/comment or one-line local edit with no architectural /
blast-radius / multi-file / "why" question. Symbol locate still uses Grep first.

## Rules

1. Include a **file path or symbol** in `context_pack` / `recall` queries when possible.
2. Packs are hints — **always verify in source** before editing.
3. Prefer fewer injected tokens over trusting noise; `recall` abstains on weak matches.
4. Optional provenance: pass `include_sources=true` on recall/context_pack when debugging trust.
5. If graph looks empty/wrong, check `brain_stats` — stale graphs auto-queue refresh, or run
   `brainkm graph sync`.
6. Grep finding a file does **not** replace recall/traverse/context_pack for decisions /
   blast-radius / multi-file context.

## Lifecycle (mental model)

`observation` → `episode` → semantic `memory` → `procedure`, with `about_file` / `about_symbol` / `mentions_concept` edges linking chat truth to code.
