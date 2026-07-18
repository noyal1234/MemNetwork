---
name: brainkm-routing
description: >-
  When to use brainkm MCP tools (recall, context_pack, traverse) vs Claude search
  and Claude Auto Memory. Prefer file-seeded recall and verify packs in source.
  Install with brainkm install --client claude.
---

# brainkm tool routing (Claude Code)

brainkm is this project's brain (`.brain/brain.db`). It complements Claude Code — it does not replace Grep, CLAUDE.md, or Auto Memory.

## Use first

| Question | Tool |
|----------|------|
| Why did we choose X? Past decision / pivot | `recall` |
| What calls / imports X? Blast radius | `traverse` |
| Understand a module before editing 3+ files | `context_pack` (include path or symbol) |
| What did we learn about `auth.ts`? | `recall` / `context_pack` with that path |
| Pin or correct durable truth | `remember` (hooks are the primary capture path) |

## Claude native memory vs brainkm

| Layer | Role |
|-------|------|
| `CLAUDE.md` / `.claude/rules` | Authored static instructions |
| Auto Memory (`MEMORY.md`) | Claude's private notes — leave alone |
| brainkm | Searchable team decisions + Graphify + compaction survival |

Do **not** copy brainkm packs into Auto Memory. Do **not** call `remember` for ordinary session learning — hooks capture silently when `auto_observe` is on.

## Rules

1. Include a **file path or symbol** in `context_pack` / `recall` queries when possible.
2. Packs are hints — **always verify in source** before editing.
3. Prefer fewer injected tokens over trusting noise; `recall` abstains on weak matches.
4. Optional provenance: pass `include_sources=true` on recall/context_pack when debugging trust.
5. If graph looks empty/wrong, check `brain_stats` then `graph_sync`.

## Lifecycle (mental model)

`observation` → `episode` → semantic `memory` → `procedure`, with `about_file` / `about_symbol` / `mentions_concept` edges linking chat truth to code.
