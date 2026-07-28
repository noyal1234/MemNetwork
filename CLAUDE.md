# brainkm — project memory routing

Memory accumulates from **hooks** (SessionStart injection, SessionEnd distill,
PostToolUse observations). You do **not** need to call `remember` for ordinary learning.

Use the **brainkm** MCP tools:

| Question | Tool |
|----------|------|
| Why did we choose X? | `recall` |
| What calls / imports X? Impact of changing Y? | `traverse` |
| Bounded multi-file task context | `context_pack` (include a symbol or path) |
| What changed in this file recently, and why? | `trace_changes` (path) — use this instead of `git log`/Bash for a single file's history, even mid process/ops debugging |
| Pin durable truth or correct a wrong auto-capture | `remember` |

Packs are hints — always verify in source before editing.
Prefer `traverse` for blast-radius; `context_pack` before opening 3+ files.
Expand truncated ids via `recall` with `truncation_followup: true`.

Installed for Claude Code via `brainkm install --client claude`.
Frozen SessionStart context does not replace live `recall` / `traverse` /
`context_pack` / `trace_changes` — call those tools when the question matches
(load via ToolSearch first if deferred). Pass `session_id` (echoed in the
SessionStart banner and UserPromptSubmit reminder) on every call so usage
attributes correctly instead of pooling into `__anon__`.

## Coexistence with Claude native memory

| What | Where | Why |
|------|-------|-----|
| Personal prefs / debug insights | Claude Auto Memory | Per-user |
| Project architecture decisions | brainkm (`recall`) | Shared + survives compaction |
| Team coding conventions | `CLAUDE.md` / `.claude/rules` | Static policy |
| Wrong auto-captures | brainkm `remember` `action=correct` | Supersedes edge |

- **CLAUDE.md / `.claude/rules`** = authored project instructions (static).
- **Claude Auto Memory (`MEMORY.md`)** = Claude's private notes — leave alone.
- **brainkm** = searchable project brain (decisions, graph, compaction survival).
