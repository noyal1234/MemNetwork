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

### MCP tool approval (important)

Claude Code gates any server declared in a project's `.mcp.json` behind a **separate
approval from folder trust** — accepting the "trust this folder" prompt does **not**
imply approval of MCP servers inside it. Only after that second approval does the
server name land in `projects[<path>].enabledMcpjsonServers` inside the global
`~/.claude.json` (or in untracked `.claude/settings.local.json`). Until then,
Claude Code **silently skips loading the server** — no error, hooks and `.mcp.json`
both look correctly wired, but `recall` / `traverse` / `context_pack` / etc. simply
never appear.

Separately, Claude Code gates **individual MCP tools** behind
`.claude/settings.local.json` → `permissions.allow`. Server approval alone is not
enough: if only some tools are listed (e.g. `traverse` but not `recall`), Claude
will prompt on every call to the missing tools and often skips them. `brainkm
install --client claude` / `brainkm connect claude` seed **both**:

1. Server approval (`enabledMcpjsonServers`, global and/or settings.local)
2. Full tool allowlist (`mcp__brainkm__remember|recall|context_pack|traverse|brain_stats|trace_changes`)

`brainkm doctor` flags an incomplete allowlist. After changing approvals or allows,
start a **new** Claude Code session — MCP connections are established once at
session start.

HTTP entries in `.mcp.json` must also include `"type": "http"` alongside `url`.
Claude Code ≥2.1.202 treats `url` without `type` as a misconfigured stdio server and
skips it (diagnostic: `has a "url" but no "type"`). `brainkm install` / `connect`
write this field automatically.

`brainkm install --client claude` auto-approves the server for you (patches
`~/.claude.json` directly) as of the install described here — but only if the
project has already been opened in Claude Code at least once (i.e. Claude Code
has already created a `projects[<path>]` entry for it). If you run install
*before* ever opening the project in Claude Code, install will print a warning
instead of silently leaving the server unapproved:

```
Project not yet registered in ~/.claude.json — open this project in Claude Code
once (to accept the folder-trust prompt), then rerun install to auto-approve 'brainkm'.
```

If you see that warning: open the project in Claude Code once, then rerun
`brainkm install --client claude` (or just `brainkm doctor`, which re-checks and
reports the same gap without rewriting anything else). `brainkm doctor` also flags
if approval ever drifts out of sync later (e.g. someone manually disables the
server in `~/.claude.json`), and if `permissions.allow` is missing any brainkm tools.

Also note: MCP connections are established once at session start — approving the
server or expanding the tool allowlist does **not** retroactively add tools to an
already-running session. Start a **new** Claude Code session after approval to pick
up the MCP tools.

**Concurrency caveat:** if a Claude Code session for this project is already
running when you run `brainkm install --client claude`, that session holds its
own in-memory copy of `~/.claude.json` (loaded at its own startup) and may flush
it back to disk later, silently overwriting the approval patch install just made.
If `brainkm doctor` reports the approval missing again after a successful
install, close **all** running Claude Code sessions for this project, then rerun
`brainkm install --client claude` (or `brainkm doctor`) once nothing else is
running — that write will stick because nothing else can race it.

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
| `~/.claude.json` → `projects[<path>].enabledMcpjsonServers` | Global MCP-server approval (auto-patched by install; see above) |
| `.claude/settings.local.json` → `permissions.allow` | Per-tool MCP allowlist (full brainkm set seeded by install/connect) |

Verify hooks with `brainkm doctor` — Claude only loads hooks from **settings.json**.
`brainkm doctor` also verifies the `~/.claude.json` MCP approval state.

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
