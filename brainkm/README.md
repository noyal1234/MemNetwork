# brainkm

Local project brain for **agentic coding IDEs** — MCP server backed by SQLite FTS5 and a weighted knowledge graph. Same `.brain/` across hosts; Cursor / Claude Code / Antigravity / Codex are adapters (Cursor is deepest today while we dogfood there).

**Product overview** (hero, features, benchmarks, multi-host setup): see the repo root [README.md](../README.md).

**Version:** `0.8.1`

**License:** Apache-2.0 (see repo root [LICENSE](../LICENSE) and [NOTICE](../NOTICE)). Copyright © 2026 Noyal Bastin Benny.

PyPI / `uvx` install is deferred until the installable name is finalized and the repo is public. Local editable install only for now.

## Requirements

- Python **3.11+**
- See [requirements.txt](../requirements.txt) for core dependencies
- See [requirements-dev.txt](../requirements-dev.txt) for development

## Install (development)

From the MemNetwork repo root:

```bash
bash brainkm/scripts/setup_dev.sh
source .venv/bin/activate
pip install -e "./brainkm[tui]"   # optional but recommended
brainkm configure                 # guided setup — pick any apps you use
# or: brainkm install --dev --client cursor|claude|antigravity|codex|generic
brainkm version
```

Or manually:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e "./brainkm[dev,graphify]"
```

**Memory path:** hooks + `capture.auto_observe` fill the brain; MCP `remember` is pin/correct/archive only. Optional **commit trace**: `git.commit_trace` → post-commit `brainkm git-note`; MCP `trace_changes` / CLI `brainkm trace` read live git.

| Client | Hooks | MCP | Maturity note |
|--------|-------|-----|---------------|
| Cursor | `.cursor/hooks.json` | `.cursor/mcp.json` | Deepest dogfood path today |
| Claude Code | `.claude/settings.json` | project `.mcp.json` | First-class; distill via `claude -p` |
| Antigravity | `.agents/hooks.json` | `.agents/mcp_config.json` (HTTP: `serverUrl`) | First-class; Stop distill into project `.brain/` (`--project-dir` + auto-heal); extractor via `capture.distill_mode` (`agy -p` / `groq` / …) |
| Codex CLI | `.codex/hooks.json` | `.codex/config.toml` `[mcp_servers.brainkm]` | First-class; Stop → session-end; distill via `codex exec` |
| generic | CLI fallbacks | `.brain/mcp.http.example.json` or shared HTTP | MCP-only; manual capture/handover |

Claude native Auto Memory (`MEMORY.md`) stays separate — brainkm does not write it. Codex: trust the project `.codex/` layer and `/hooks` before hooks fire. Shared multi-app: Dashboard → Start Brain (or `brainkm serve` + `connect --http`). Verify with `brainkm doctor`.
## Code graph (Graphify)

Recommended for `context_pack` / `traverse` navigation:

```bash
brainkm install --dev          # attempts first graph sync
brainkm graph status
brainkm graph sync             # manual refresh after refactors
```

Optional extra: `[graphify]` installs `graphifyy` (CLI: `graphify`) in the same venv as brainkm.

## Optional dependency groups

| File / extra | Purpose |
|--------------|---------|
| `requirements-dev.txt` / `[dev]` | pytest, ruff |
| `requirements-graphify.txt` / `[graphify]` | Graphify AST extract (`graphifyy`) |
| `requirements-semantic.txt` / `[semantic]` | T1 onnxruntime + sqlite-vec (off by default) |

```bash
pip install -e "./brainkm[dev,graphify,semantic]"
```
