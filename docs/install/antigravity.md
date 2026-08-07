# Google Antigravity + brainkm

First-class Antigravity adapter under **`.agents/`**. HTTP MCP uses **`serverUrl`** (not `url`). Stop distill is forced into the **project** `.brain/` even when hook cwd is `.agents/`.

**Shared brain:** same `.brain/brain.db` as Cursor / Claude / Codex.  
**Clone once:** [INSTALL.md](../INSTALL.md) · then wire this host.

---

## What is exclusive to Antigravity

| Surface | Antigravity-specific behavior |
|---------|-------------------------------|
| **MCP** | `.agents/mcp_config.json` — shared HTTP field is **`serverUrl`** |
| **Hooks** | `.agents/hooks.json` — named `brainkm` handler; `preInvocation`, `preToolUse`, `postToolUse`, idle **Stop** |
| **Rules / skill** | `.agents/rules/brainkm.md` (**requires** `trigger: always_on` YAML frontmatter) + routing skill; also upserts repo-root `AGENTS.md` snippet |
| **No host PreCompact** | Synthetic precompact on **PreInvocation** instead |
| **Project-dir bake** | Stop / PreInvocation commands embed absolute `--project-dir` so distill never lands in a shadow `.agents/.brain` |
| **Auto-heal** | `doctor` / PreInvocation rewrite missing `--project-dir`; merge `agy_sessions.json` then remove leftover shadow brain |
| **Distill peer** | `capture.distill_mode: antigravity` → `agy -p` (or `groq` / `ollama` for shared extractors) |
| **Secrets** | Put `GROQ_API_KEY` etc. in the **project** `.env` — hooks load it via `--project-dir` |
| **Optional global MCP** | `brainkm connect antigravity --http --mirror-global` → `~/.gemini/config/mcp_config.json` |

Grant `mcp(brainkm/*)` so tools are not stuck in Ask mode. Do not stack Mem0 (or similar) on the same project.

---

## Install

```bash
# Guided (recommended)
pip install -e "./brainkm[tui]"
brainkm configure   # check Antigravity

# Or CLI
brainkm install --dev --client antigravity
brainkm doctor
```

Reload Antigravity / MCP. Dashboard shows AGY hooks when `.agents/` is present.

### Shared with another IDE

```bash
brainkm configure   # multi-app → Start Brain
# or:
brainkm serve
brainkm connect antigravity --http --hooks
```

---

## After install

| Path | Role |
|------|------|
| `.agents/mcp_config.json` | MCP (`serverUrl` for HTTP) |
| `.agents/hooks.json` | PreInvocation inject + Stop distill |
| `.agents/rules/brainkm.md` + skill | Always-on routing (`trigger: always_on` frontmatter required) |
| Project `.brain/` | Live brain — **not** `.agents/.brain` |

If a shadow `.agents/.brain` appears, run `brainkm doctor` (or reconnect) so auto-heal can merge and remove it.

---

## Coexistence

| Layer | Role |
|-------|------|
| `.agents/rules` / `AGENTS.md` | Authored static instructions |
| Host codebase index | Symbol locate |
| brainkm | Decisions, graph, session survival across hosts |

---

## See also

- [INSTALL.md](../INSTALL.md) — clone + multi-host overview  
- [FEATURES.md](../FEATURES.md) — hook parity matrix  
- [Cursor](cursor.md) · [Claude Code](claude-code.md) · [Codex](codex.md) · [Generic MCP](generic.md)
