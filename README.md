# MemNetwork (brainkm)

**Faster, smarter project memory for coding agents** — a local SQLite brain that cuts token usage and feeds high-quality context to Cursor, Claude Code, or any MCP client.

| Dial | What brainkm does |
|------|-------------------|
| **Tokens** | Bounded `context_pack` (default ≤1500) with summary-first gists + adaptive intent budgets |
| **Quality** | Hybrid FTS + vector RRF, weighted PPR graph activation, conflict/supersede, usage feedback |
| **Speed** | Local retrieval latency targets (p95 ≤150ms recall without reranker) |
| **Reach** | Guided TUI (`brainkm configure`): pick apps → auto stdio or shared brain; Semantic Quality consent; hooks fill memory |

## Docs

- [AGENTS.md](AGENTS.md) — agent entry point
- [docs/FEATURES.md](docs/FEATURES.md) — product feature catalog (what brainkm does and why)
- [docs/INSTALL.md](docs/INSTALL.md) — clone + local editable setup
- [docs/AI_PROJECT_BRIEF.md](docs/AI_PROJECT_BRIEF.md) — architecture + roadmap
- [docs/BENCHMARKS.md](docs/BENCHMARKS.md) — CMA public scorecard + product eval targets
- [docs/SECURITY.md](docs/SECURITY.md) — inbound/outbound redaction posture
- [docs/CLI_COMMANDS.md](docs/CLI_COMMANDS.md) — CLI catalog
- [docs/TUI_APP_PLAN.md](docs/TUI_APP_PLAN.md) — `brainkm configure` TUI

## Quick start (local / private repo)

```bash
bash brainkm/scripts/setup_dev.sh
source .venv/bin/activate
pip install -e "./brainkm[tui]"
brainkm configure   # recommended: pick apps, silent memory, Start Brain if sharing
# or: brainkm install --dev --client cursor
brainkm version
```

One app → Cursor/Claude starts the brain for you. Two+ apps → shared localhost brain (Start Brain once from the TUI). Use `--dev` while the repo is private.

Optional semantic hybrid retrieval (wizard can recommend and enable with consent):

```bash
pip install -e "./brainkm[semantic]"
brainkm semantic doctor
# or set "semantic": {"enabled": true} after downloading MiniLM via wizard / ensure cache
```

### Deferred until public + stable

PyPI / `uvx brainkm install`, MCP Registry listing, Cursor one-click deeplink, and a trusted-publishing release workflow are **intentionally deferred** while this repository stays private. Revisit after a stable cut is ready to open-source.

## vs Cursor Memories / Claude Auto Memory / @codebase / Mem0

| Job | Prefer |
|-----|--------|
| Cross-project user prefs | Cursor Memories |
| Claude's private notes | Claude Auto Memory (`MEMORY.md`) — leave alone |
| Authored Claude project rules | `CLAUDE.md` / `.claude/rules` |
| "Where is symbol X?" | @codebase / Grep |
| "Why did we choose X?" | **brainkm `recall`** |
| "What calls X?" | **brainkm `traverse` / `context_pack`** |
| Hosted multi-tenant memory | Mem0 / Zep — not the goal here |

brainkm is **local-first**, **zero-LLM-default** (`rules` distill), and complementary to Cursor / Claude / Antigravity — not a second codebase index. Claude → `.claude/settings.json`; Antigravity → `.agents/` (`serverUrl` for HTTP). See [INSTALL.md](docs/INSTALL.md).


## Status

**brainkm 0.4.2** — Antigravity first-class client (`.agents/` MCP `serverUrl` + hooks, PreInvocation inject, `agy -p` distill) + foolproof `claude` distill (`claude -p`; legacy `mcp` alias) on top of 0.4.1 Claude silent memory. 8 MCP tools, shared localhost brain, multi-client install (Cursor / Claude / Antigravity / Codex) + guided TUI. See [docs/AI_PROJECT_BRIEF.md](docs/AI_PROJECT_BRIEF.md).
