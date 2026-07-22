# MemNetwork (brainkm)

This project uses **brainkm** — a local SQLite project brain at `.brain/brain.db`.

## Before reading many files

- **MUST call** MCP **`traverse`** for call/import/flow and blast-radius questions ("what calls X?", "what breaks if I change Y?") — pass a symbol or path before editing multi-file code.
- **MUST call** MCP **`trace_changes`** for "what changed in this file recently and why?" — live git log joined to commit↔session↔decision links.
- **MUST call** MCP **`context_pack`** for multi-file task context (include a symbol or file path in the query or `seed_refs`), then verify in source before editing.
- **MUST call** MCP **`recall`** for architectural decisions, rules, and past pivots before proposing architectural changes.
- Memory accumulates from **hooks** (PreInvocation inject, Stop distill, PostToolUse observations). Call **`remember` only to pin** durable project truth or **correct** a wrong auto-capture.

## Tool routing (locate vs flow vs decisions)

| Question type | Use first | Why |
|---------------|-----------|-----|
| "Where is symbol X defined?" | Grep / project search | Semantic/symbol locate |
| "What calls / imports X?" / "impact of changing Y" | **`traverse`** (symbol/path), then verify | Focused AST neighborhood |
| "What changed in file Y recently / why?" | **`trace_changes`** (path) | Live git timeline + commit joins |
| "Why did we choose X?" | **`recall`** | Decisions live in neurons, not the code index |
| Understand one module (would open 3+ files) | **`context_pack`** then targeted reads | Bounded pack vs file dumps |

Do **not** treat brainkm as a second project search index. Use Grep/search to **locate**; use Graphify (`traverse` for flow, `context_pack` for task packs) to explain structure. Never skip reading source because a pack abstained or looked incomplete — prefer fewer injected tokens over trusting noise.

If `traverse` / `context_pack` results look empty or wrong, check **`brain_stats`** first — a stale or missing code graph is the usual cause; reads auto-queue a refresh, or run `brainkm graph sync`. Empty `traverse` responses include a `hint`, `resolved_id`, and `impact_summary` when the graph matched but had no neighbors.

## 🚨 MANDATORY BRAINKM ROUTING FOR ANTIGRAVITY
1. **BEFORE proposing architectural changes or refactors**, you MUST execute `mcp_brainkm_recall` to fetch past architectural decisions.
2. **BEFORE editing functions across multiple files**, you MUST execute `mcp_brainkm_traverse` with the symbol/path to analyze blast radius and dependencies.
3. **BEFORE modifying existing files**, check `mcp_brainkm_trace_changes` for recent commits and decision context.

## MANDATORY BRAINKM TOOL ROUTING (Antigravity)

Dispatch brainkm tools via Antigravity's lazy MCP wrapper: `call_mcp_tool` with server
`brainkm` and tool name `recall` / `traverse` / `context_pack` / `trace_changes` /
`brain_stats` / `remember`. Do **not** invent names like `mcp_brainkm_recall`.

1. Blast-radius / "what calls X" / impact of changing Y: you **MUST** call `traverse`
   (pass a symbol or path). **Never** rely on text search alone for call/import flow.
2. "Why did we choose X" / past decisions / pivots: you **MUST** call `recall` unless the
   PreInvocation ephemeral pack already answers that **exact** question.
3. Before opening 3+ files for one module/task: you **MUST** call `context_pack` (include
   a path or symbol), then verify in source.
4. Git history joins / "what changed in this file and why": you **MUST** call
   `trace_changes`.
5. PreInvocation injects a **frozen** snapshot. If it is insufficient for the current
   question, you **MUST** still call the live tool — the ephemeral message is **not** a
   substitute for `traverse`, `trace_changes`, or a fresh `recall` / `context_pack`.

Symbol locate ("where is X defined?") still uses Grep / project search first — do **not**
force `recall` before every search or file read.

## What lives in the brain

| Store | Contents |
|-------|----------|
| Neurons (`memory`) | Decisions, rules, facts, errors, context |
| Code graph (`code`) | Graphify AST nodes — files, classes, functions, edges |
| Session chunks | Raw transcript search index (distilled into neurons) |

## Permissions

Grant **`mcp(brainkm/*)`** (or always-allow brainkm tools) so recall/context_pack are not stuck in Ask mode.

## Coexistence

- **`.agents/rules` / `AGENTS.md`** = authored static instructions.
- **brainkm** = searchable project decisions, code graph, session survival.
- Do **not** stack Mem0 (or similar memory MCP) with brainkm on the same project.
- Shared with Cursor / Claude: one `brainkm serve` + `connect --http` (AGY MCP field is `serverUrl`).

## Lifecycle (Antigravity)

- **PreInvocation** injects a throttled frozen pack (`injectSteps.ephemeralMessage`) and auto-heals wiring (hooks `--project-dir`, shadow `.agents/.brain`).
- **Stop** (when fully idle) distills into the **project** `.brain/` (not `.agents/.brain`). Hooks bake absolute `--project-dir`; stdin `workspacePaths` is a fallback.
- HTTP shared brain uses **`serverUrl`** in `.agents/mcp_config.json` (not `url`).
- Distill extractor is project-wide `capture.distill_mode` (e.g. `groq` or `antigravity` / `agy -p`). Put `GROQ_API_KEY` in the project `.env`.

## Manual fallback (hooks unavailable)

```bash
brainkm handover path/to/transcript.jsonl   # before compact / long turn
brainkm capture path/to/transcript.jsonl      # after session
brainkm graph sync                            # refresh code graph (extract + import)
brainkm graph sync --skip-extract             # import existing graph.json only
brainkm hygiene                               # soft-archive noisy auto-captured neurons
```

Auto-sync runs in the MCP server after write/edit (debounced). Disable via `.brain/config.json`:
`"graphify": { "auto_sync": { "enabled": false } }`.
