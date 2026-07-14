# MemNetwork

Local project brain for Cursor — **brainkm** MCP server (SQLite FTS5 + weighted knowledge graph).

## Docs

- [AGENTS.md](AGENTS.md) — agent entry point
- [docs/INSTALL.md](docs/INSTALL.md) — clone, setup, and MCP install on another machine
- [docs/AI_PROJECT_BRIEF.md](docs/AI_PROJECT_BRIEF.md) — architecture, MCP contract, roadmap
- [docs/CLI_COMMANDS.md](docs/CLI_COMMANDS.md) — full CLI catalog
- [docs/TUI_APP_PLAN.md](docs/TUI_APP_PLAN.md) — `brainkm configure` Textual dashboard (shipped)

## Quick start

```bash
bash brainkm/scripts/setup_dev.sh
source .venv/bin/activate
brainkm install --dev
pytest
brainkm version
brainkm graph status
# optional: Textual config UI
pip install -e "./brainkm[tui]"
brainkm configure
```

See [docs/INSTALL.md](docs/INSTALL.md) for the full clone-to-MCP flow.

Python **3.11 or 3.12** recommended (`requires-python = ">=3.11"`).

## Layout

| Path | Purpose |
|------|---------|
| `brainkm/` | Python package (MCP server + CLI + optional TUI) |
| `.cursor/rules/` | Cursor policy rules + `brainkm.mdc` (gitignored, local only) |
| `cursor-policy/` | Notes on Cursor policy layout (see README) |
| `.cursor/skills/memnetwork-backend/` | Cursor skill for backend work |
| `docs/AI_PROJECT_BRIEF.md` | Product + technical brief |

## Requirements

| File | Purpose |
|------|---------|
| [brainkm/pyproject.toml](brainkm/pyproject.toml) | Source of truth (editable install, extras) |
| [requirements.txt](requirements.txt) | Core runtime (pip -r) |
| [requirements-dev.txt](requirements-dev.txt) | Dev + test |
| [requirements-graphify.txt](requirements-graphify.txt) | Optional Graphify AST extract |
| [requirements-semantic.txt](requirements-semantic.txt) | Optional T1 embeddings |

## Status

**brainkm 0.2.0** — SQLite brain, 8 MCP tools, hooks, install, Graphify import/sync, capture/handover, repair/export/import merge, post-compact snapshot refresh, learning loop (co-activation + procedure promotion), confidence-gated review queue, neuron hygiene, end-to-end token budgeting with lean MCP payloads, MCP usage telemetry, fixture-driven bench suites, and the optional `brainkm configure` Textual TUI (`pip install -e "./brainkm[tui]"`). **V3+ planned:** decay, optional semantic search. See [docs/AI_PROJECT_BRIEF.md](docs/AI_PROJECT_BRIEF.md) for roadmap.
