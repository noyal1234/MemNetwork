# OpenAI Codex CLI + brainkm

First-class Codex adapter: MCP lives in **`.codex/config.toml`** (not JSON `mcp.json`). Codex has **no SessionEnd** — **Stop** runs session-end capture. Project hooks require an explicit trust step.

**Shared brain:** same `.brain/brain.db` as Cursor / Claude / Antigravity.  
**Clone once:** [INSTALL.md](../INSTALL.md) · then wire this host.

---

## Required: trust hooks (easy to miss)

Codex treats **MCP** and **hooks** as separate trust surfaces:

| What you see | What it means |
|--------------|---------------|
| `brainkm` MCP **enabled** (gear may look **locked**) | Project `.codex/config.toml` loaded — tools can work |
| Hooks **not** trusted yet | SessionStart / Stop / PreCompact / PostToolUse are **skipped** — no capture or inject |

Until you trust hooks, the brain looks “installed” but stays quiet. Do both:

1. Trust this project’s `.codex/` config layer (so MCP + project config load).
2. In Codex, open **`/hooks`** and trust the brainkm commands (they run your local `.venv/bin/brainkm … --client codex`).

Inspect what you are trusting: the template at `brainkm/brainkm/hooks/codex/hooks.json` (install copies absolute paths into project `.codex/hooks.json`). Verify with `brainkm doctor`.

---

## What is exclusive to Codex

| Surface | Codex-specific behavior |
|---------|-------------------------|
| **MCP** | `.codex/config.toml` → `[mcp_servers.brainkm]` (stdio or HTTP + `http_headers`) |
| **Hooks** | `.codex/hooks.json` — PascalCase nested schema |
| **Trust gate** | Trust the project’s `.codex/` layer, then open **`/hooks`** in Codex and trust brainkm commands — untrusted project hooks are **skipped** |
| **No SessionEnd** | **Stop** → session-end distill / promote |
| **Compaction** | PreCompact + PostCompact |
| **Rules / skill** | Upserts `AGENTS.md`; installs `.codex/skills/` routing skill |
| **Distill peer** | `capture.distill_mode: codex` → `codex exec --sandbox read-only --ask-for-approval never` (falls back to `rules` if CLI missing) |
| **Transcripts** | Codex rollout JSONL |

---

## Install

```bash
# Guided (recommended)
pip install -e "./brainkm[tui]"
brainkm configure   # check Codex

# Or CLI
brainkm install --dev --client codex
brainkm doctor
```

Then in Codex (required — see [trust hooks](#required-trust-hooks-easy-to-miss) above):

1. Trust this project’s `.codex/` config layer.  
2. Open `/hooks` and trust the brainkm hook commands.

### Shared with another IDE

```bash
brainkm configure
# or:
brainkm serve
brainkm connect codex --http --hooks
```

---

## After install

| Path | Role |
|------|------|
| `.codex/config.toml` | `[mcp_servers.brainkm]` |
| `.codex/hooks.json` | Stop → session-end, compact, tool observe |
| `AGENTS.md` + `.codex/skills/` | Static instructions + routing |
| `.brain/` | Live SQLite brain |

`brainkm doctor` surfaces trust / `/hooks` notes when wiring looks incomplete.

---

## Coexistence

| Layer | Role |
|-------|------|
| `AGENTS.md` | Authored project instructions |
| Host / Codex tools | Editing and symbol work |
| brainkm | Decisions, graph, session survival across hosts |

---

## See also

- [INSTALL.md](../INSTALL.md) — clone + multi-host overview  
- [FEATURES.md](../FEATURES.md) — hook parity matrix  
- [Cursor](cursor.md) · [Claude Code](claude-code.md) · [Antigravity](antigravity.md) · [Generic MCP](generic.md)
