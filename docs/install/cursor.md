# Cursor + brainkm

Deepest dogfood path today: native PreCompact handover, SessionEnd distill, and `.cursor/` wiring.

**Shared brain:** same `.brain/brain.db` as Claude / Antigravity / Codex.  
**Clone once:** [INSTALL.md](../INSTALL.md) · then wire this host.

---

## What is exclusive to Cursor

| Surface | Cursor-specific behavior |
|---------|--------------------------|
| **MCP** | `.cursor/mcp.json` — stdio by default (`brainkm mcp`); HTTP via `url` when sharing |
| **Hooks** | `.cursor/hooks.json` — `sessionStart`, `sessionEnd`, `preCompact`, `postToolUse`, `beforeSubmitPrompt` |
| **Rules** | `.cursor/rules/brainkm.mdc` (+ local `memnetwork-*.mdc` policy; not always git-tracked) |
| **Compaction** | Host **PreCompact** → `brainkm handover` before Cursor loses chat context |
| **Distill peer** | `capture.distill_mode: cursor` (Agent CLI when available; else heuristics) |
| **Transcripts** | Cursor agent JSONL under the host transcript store |
| **Plans** | Optional ingest of `.cursor/plans/*.plan.md` into neurons |

Cursor Memories / `@codebase` stay separate: Memories = cross-project prefs; `@codebase` = symbol search. brainkm stores **this project’s** decisions and graph structure.

---

## Install

```bash
# Guided (recommended)
pip install -e "./brainkm[tui]"
brainkm configure   # check Cursor

# Or CLI
brainkm install --dev --client cursor
brainkm doctor
```

Reload MCP servers (or restart Cursor). Verify with `brainkm version` and MCP tool list (`recall`, `context_pack`, …).

### Shared with another IDE

```bash
brainkm configure          # check Cursor + others → Start Brain
# or: brainkm serve && brainkm connect cursor --http
```

---

## After install

| Path | Role |
|------|------|
| `.cursor/mcp.json` | MCP server entry (may use absolute venv path) |
| `.cursor/hooks.json` | Capture / inject / PreCompact |
| `.cursor/rules/brainkm.mdc` | Tool-routing policy for the agent |
| `.brain/` | Live SQLite brain (gitignored) |

Templates (shape only): [`.cursor/mcp.json.example`](../../.cursor/mcp.json.example), [`.cursor/hooks.json.example`](../../.cursor/hooks.json.example).

---

## Coexistence

| Layer | Role |
|-------|------|
| Cursor Memories | Cross-project prefs — do not duplicate in neurons |
| Cursor Rules | Static team policy |
| `@codebase` / Grep | Locate symbols — then `traverse` / `context_pack` for structure |
| brainkm | Decisions, compaction survival, AST neighborhood |

---

## See also

- [INSTALL.md](../INSTALL.md) — clone + multi-host overview  
- [FEATURES.md](../FEATURES.md) — hook parity matrix  
- [Claude Code](claude-code.md) · [Antigravity](antigravity.md) · [Codex](codex.md) · [Generic MCP](generic.md)
