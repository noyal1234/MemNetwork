# brainkm

Local project brain for Cursor — MCP server backed by SQLite FTS5 and a weighted knowledge graph.

**Version:** `0.4.0`

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
brainkm configure                 # guided setup (or: brainkm install --dev)
brainkm version
```

Or manually:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e "./brainkm[dev,graphify]"
```

**Memory path:** hooks + `capture.auto_observe` fill the brain; MCP `remember` is pin/correct only. Shared multi-app: Dashboard → Start Brain (or `brainkm serve` + `connect --http`).
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
