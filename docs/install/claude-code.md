# Claude Code + brainkm

First-class Claude Code adapter: hooks live in **`.claude/settings.json`** (not `.claude/hooks.json`), MCP in project **`.mcp.json`**, plus Subagent and PostCompact parity.

**Shared brain:** same `.brain/brain.db` as Cursor / Antigravity / Codex.  
**Clone once:** [INSTALL.md](../INSTALL.md) · then wire this host.

---

## What is exclusive to Claude Code

| Surface | Claude-specific behavior |
|---------|--------------------------|
| **MCP** | Project-root `.mcp.json` (Claude’s project MCP file) |
| **Hooks** | `.claude/settings.json` — PascalCase events; **not** a separate `hooks.json` |
| **Rules / skill** | `.claude/rules/brainkm.md` + routing skill; upserts `CLAUDE.md` |
| **Injection** | SessionStart / SubagentStart via `hookSpecificOutput` |
| **Compaction** | PreCompact handover **and** PostCompact refresh |
| **Extra events** | `PostToolUseFailure`, `SubagentStart` / `SubagentStop`, `Stop` |
| **Distill peer** | `capture.distill_mode: claude` → `claude -p` (+ MCP sampling when live); legacy `mcp` → `claude` |
| **Transcripts** | Claude JSONL capture path |

Claude **Auto Memory** (`MEMORY.md`) stays private to Claude — brainkm does **not** write it. Prefs/debug notes → Auto Memory; durable team decisions → brainkm.

---

## Install

```bash
# Guided (recommended)
pip install -e "./brainkm[tui]"
brainkm configure   # check Claude Code

# Or CLI
brainkm install --dev --client claude
brainkm doctor
```

Reload Claude Code / MCP. Dashboard shows Claude hooks status when `.claude/settings.json` is present.

### Shared with another IDE

```bash
brainkm configure
# or: brainkm serve && brainkm connect claude --http --hooks
```

---

## After install

| Path | Role |
|------|------|
| `.mcp.json` | Project MCP server entry |
| `.claude/settings.json` | Hooks (SessionStart → Stop / Subagent / compact) |
| `.claude/rules/` + skill | Tool-routing policy |
| `CLAUDE.md` | Static instructions upsert (coexists with Auto Memory) |
| `.brain/` | Live SQLite brain |

Verify hooks with `brainkm doctor` — Claude only loads hooks from **settings.json**.

---

## Coexistence

| Layer | Role |
|-------|------|
| `CLAUDE.md` / `.claude/rules` | Authored static project instructions |
| Claude Auto Memory | Private notes — leave alone |
| Host codebase tools | Symbol locate |
| brainkm | Searchable decisions, graph, compaction survival |

---

## See also

- [INSTALL.md](../INSTALL.md) — clone + multi-host overview  
- [FEATURES.md](../FEATURES.md) — hook parity matrix  
- [Cursor](cursor.md) · [Antigravity](antigravity.md) · [Codex](codex.md) · [Generic MCP](generic.md)
