---
name: brainkm-routing
description: >-
  When to use brainkm MCP tools (recall, context_pack, traverse, trace_changes,
  feedback) vs project search. Prefer file-seeded recall and verify packs in
  source. Install with brainkm install.
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
| Prior recall/pack node was clearly the answer or wrong | `feedback` (`signal=used\|wrong` on those `node_id`s; skip routine packs) |
| **Something is broken** — error text, traceback, "not firing", "went silent" | `recall` with the raw error/symptom **first**, before hand-debugging |
| "This worked before — what broke it?" | `trace_changes` (regression bisect) |
| You just solved a non-obvious failure | `remember` (`subtype=error`) — else it stays a raw chunk and won't rank |

## MUST (Claude Code)

1. Blast-radius / call/import flow: you **MUST** call `traverse` — never text search alone.
2. Decisions / "why X": you **MUST** call `recall`. The SessionStart pack is a hint only —
   never a substitute for the live call, even if it looks like it already answers the question.
3. Before opening 3+ files for one task: you **MUST** call `context_pack`, then verify in source.
4. "What changed in this file and why": you **MUST** call `trace_changes`.
5. SessionStart pack is frozen — if insufficient, you **MUST** still call the live tool.
   Tools are deferred: call `ToolSearch` **once** at session start to load all seven brainkm
   schemas, not per-tool. Pass `session_id` on every call.

**Bypass is narrow, not a default:** only a pure mechanical edit (typo, rename, formatting)
with zero judgment calls. Anything touching more than one file, changing behavior, or requiring
you to explain *why*/*what breaks*/*what changed* is not this case — call the tool. When in
doubt, call it.

## Rules

1. Include a **file path or symbol** in `context_pack` / `recall` queries when possible.
2. Packs are hints — **always verify in source** before editing.
3. Prefer fewer injected tokens over trusting noise; `recall` abstains on weak matches.
4. Optional provenance: pass `include_sources=true` on recall/context_pack when debugging trust.
5. If graph looks empty/wrong, check `brain_stats` — stale graphs auto-queue refresh, or run
   `brainkm graph sync`.
6. Grep finding a file does **not** replace recall/traverse/context_pack for decisions /
   blast-radius / multi-file context.
7. After a recall/pack clearly helped (or misled), call `feedback` — do **not** call
   `checkpoint` (PreCompact already handovers).

## Lifecycle (mental model)

`observation` → `episode` → semantic `memory` → `procedure`, with `about_file` / `about_symbol` / `mentions_concept` edges linking chat truth to code.
