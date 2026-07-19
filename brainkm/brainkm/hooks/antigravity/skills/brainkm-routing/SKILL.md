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

## Rules

1. Include a **file path or symbol** in `context_pack` / `recall` queries when possible.
2. Packs are hints — **always verify in source** before editing.
3. Prefer fewer injected tokens over trusting noise; `recall` abstains on weak matches.
4. If graph looks empty/wrong, check `brain_stats` then `graph_sync`.
5. Ensure brainkm MCP tools are allowed (`mcp(brainkm/*)`); do not stack Mem0 with brainkm.
