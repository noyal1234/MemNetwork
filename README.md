# MemNetwork (brainkm)

**Faster, smarter project memory for coding agents** — a local SQLite brain that cuts token usage and feeds high-quality context to Cursor, Claude Code, or any MCP client.

| Dial | What brainkm does |
|------|-------------------|
| **Tokens** | Bounded `context_pack` (default ≤1500) with summary-first gists + adaptive intent budgets |
| **Quality** | Hybrid FTS + vector RRF, weighted PPR graph activation, conflict/supersede, usage feedback |
| **Speed** | Local retrieval latency targets (p95 ≤150ms recall without reranker) |
| **Reach** | `brainkm install --client …` / TUI wizard Agent Client step + optional HTTP MCP |

## Docs

- [AGENTS.md](AGENTS.md) — agent entry point
- [docs/INSTALL.md](docs/INSTALL.md) — clone + local editable setup
- [docs/AI_PROJECT_BRIEF.md](docs/AI_PROJECT_BRIEF.md) — architecture + roadmap
- [docs/BENCHMARKS.md](docs/BENCHMARKS.md) — bench targets
- [docs/SECURITY.md](docs/SECURITY.md) — inbound/outbound redaction posture
- [docs/CLI_COMMANDS.md](docs/CLI_COMMANDS.md) — CLI catalog
- [docs/TUI_APP_PLAN.md](docs/TUI_APP_PLAN.md) — `brainkm configure` TUI

## Quick start (local / private repo)

```bash
bash brainkm/scripts/setup_dev.sh
source .venv/bin/activate
brainkm install --dev --client cursor
# or: pip install -e "./brainkm[tui]" && brainkm configure  # wizard Agent Client picker
brainkm version
```

MCP config is written for the selected client (`cursor` / `claude` / `generic`). Use `--dev` while the repo is private.

Optional semantic hybrid retrieval: `pip install -e "./brainkm[semantic]"` then set `"semantic": {"enabled": true}` in `.brain/config.json`.

### Deferred until public + stable

PyPI / `uvx brainkm install`, MCP Registry listing, Cursor one-click deeplink, and a trusted-publishing release workflow are **intentionally deferred** while this repository stays private. Revisit after a stable cut is ready to open-source.

## vs Cursor Memories / @codebase / Mem0

| Job | Prefer |
|-----|--------|
| Cross-project user prefs | Cursor Memories |
| "Where is symbol X?" | @codebase / Grep |
| "Why did we choose X?" | **brainkm `recall`** |
| "What calls X?" | **brainkm `traverse` / `context_pack`** |
| Hosted multi-tenant memory | Mem0 / Zep — not the goal here |

brainkm is **local-first**, **zero-LLM-default** (`rules` distill), and complementary to Cursor — not a second codebase index.

## Status

**brainkm 0.3.1** — 8 MCP tools + resources, hybrid retrieval (RRF + PPR), intent routing, compression/dedup/summary-first packs, feedback ranking, decay/consolidate, multi-client install (`--client` CLI + TUI wizard Agent Client step), optional HTTP transport, latency bench, team neuron layer, import `--replace`. See [docs/AI_PROJECT_BRIEF.md](docs/AI_PROJECT_BRIEF.md) and [docs/BENCHMARKS.md](docs/BENCHMARKS.md).
