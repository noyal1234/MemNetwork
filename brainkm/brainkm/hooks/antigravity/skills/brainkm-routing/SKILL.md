---
name: brainkm-routing
description: >-
  When to use brainkm MCP tools (recall, context_pack, traverse) vs Antigravity
  search. Prefer file-seeded recall and verify packs in source. Install with
  brainkm install --client antigravity. Use when the user asks about past
  decisions, architecture pivots, or blast-radius of a change.
---

# brainkm tool routing (Antigravity)

brainkm is this project's brain (`.brain/brain.db`). It complements Antigravity — it does not replace grep, rules, or AGENTS.md.

## Use first

| Question | Tool |
|----------|------|
| Why did we choose X? Past decision / pivot | `recall` |
| What calls / imports X? Blast radius | `traverse` |
| Understand a module before editing 3+ files | `context_pack` (include path or symbol) |
| Pin or correct durable truth | `remember` (hooks are the primary capture path) |

## Host wiring

| Path | Role |
|------|------|
| `.agents/mcp_config.json` | MCP (HTTP field: `serverUrl`) |
| `.agents/hooks.json` | Named `brainkm` handler (PreInvocation / tools / Stop) |
| `.agents/rules` + `AGENTS.md` | Static instructions |
| brainkm | Searchable decisions + Graphify + session survival |

Inject-first (hooks), MCP-second (deep recall). Do **not** call `remember` for ordinary learning when `auto_observe` is on.

Do **not** treat brainkm as a second search index. Use Grep to locate; use `traverse` / `context_pack` for structure.

## Rules

1. Include a **file path or symbol** in `context_pack` / `recall` queries when possible.
2. Packs are hints — **always verify in source** before editing.
3. Prefer fewer injected tokens over trusting noise; `recall` abstains on weak matches.
4. Optional provenance: pass `include_sources=true` on recall/context_pack when debugging trust.
5. If graph looks empty/wrong, check `brain_stats` then `graph_sync`.
6. Ensure brainkm MCP tools are allowed (`mcp(brainkm/*)`); do not stack Mem0 with brainkm.
7. Soft-archive noisy auto-captures with `brainkm hygiene` rather than injecting junk.

## What lives in the brain

| Store | Contents |
|-------|----------|
| Neurons (`memory`) | Decisions, rules, facts, errors, context |
| Code graph (`code`) | Graphify AST nodes — files, classes, functions, edges |
| Session chunks | Raw transcript search index (distilled into neurons) |

## Lifecycle (mental model)

`observation` → `episode` → semantic `memory` → `procedure`, with `about_file` / `about_symbol` / `mentions_concept` edges linking chat truth to code.

Antigravity hooks: PreInvocation inject (throttled) → PostToolUse observe → idle Stop distill (synthetic precompact on long turns).
