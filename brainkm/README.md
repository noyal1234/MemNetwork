# brainkm

Local project brain for Cursor and Claude Code — MCP server backed by SQLite FTS5 and a weighted knowledge graph.

**Version:** `0.4.1`

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
brainkm configure                 # guided setup (pick Cursor / Claude / Codex)
# or: brainkm install --dev --client claude
brainkm version
```

Or manually:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e "./brainkm[dev,graphify]"
```

**Memory path:** hooks + `capture.auto_observe` fill the brain; MCP `remember` is pin/correct only.

| Client | Hooks | MCP |
|--------|-------|-----|
| Cursor | `.cursor/hooks.json` | `.cursor/mcp.json` |
| Claude Code | `.claude/settings.json` | project `.mcp.json` |

Claude native Auto Memory (`MEMORY.md`) stays separate — brainkm does not write it. Shared multi-app: Dashboard → Start Brain (or `brainkm serve` + `connect --http`). Verify Claude with `brainkm doctor`.
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
