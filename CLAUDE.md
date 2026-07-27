# brainkm — project memory routing

Memory accumulates from **hooks** (SessionStart injection, SessionEnd distill,
PostToolUse observations). You do **not** need to call `remember` for ordinary learning.

Use the **brainkm** MCP tools:

| Question | Tool |
|----------|------|
| Why did we choose X? | `recall` |
| What calls / imports X? Impact of changing Y? | `traverse` |
| Bounded multi-file task context | `context_pack` (include a symbol or path) |
| Pin durable truth or correct a wrong auto-capture | `remember` |

Packs are hints — always verify in source before editing.
Prefer `traverse` for blast-radius; `context_pack` before opening 3+ files.
Expand truncated ids via `recall` with `truncation_followup: true`.

Installed for Claude Code via `brainkm install --client claude`.

## Coexistence with Claude native memory

- **CLAUDE.md / `.claude/rules`** = authored project instructions (static).
- **Claude Auto Memory (`MEMORY.md`)** = Claude's private notes — leave alone.
- **brainkm** = searchable project brain (decisions, graph, compaction survival).
Prefs/debug notes stay in Auto Memory; durable team decisions → brainkm MCP.
