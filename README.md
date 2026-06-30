# MemNetwork

Local project brain for Cursor — **brainkm** MCP server (SQLite FTS5 + weighted knowledge graph).

## Docs

- [AGENTS.md](AGENTS.md) — agent entry point
- [docs/INSTALL.md](docs/INSTALL.md) — clone, setup, and MCP install on another machine
- [docs/AI_PROJECT_BRIEF.md](docs/AI_PROJECT_BRIEF.md) — architecture, MCP contract, roadmap

## Quick start

```bash
bash brainkm/scripts/setup_dev.sh
source .venv/bin/activate
brainkm install --dev
pytest
brainkm version
brainkm graph status
```

See [docs/INSTALL.md](docs/INSTALL.md) for the full clone-to-MCP flow.

Python **3.11 or 3.12** recommended (`requires-python = ">=3.11"`).

## Layout

| Path | Purpose |
|------|---------|
| `brainkm/` | Python package (MCP server + CLI) |
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

**V1** — SQLite brain, MCP tools, hooks, install, Graphify import/sync, capture/handover. See [docs/AI_PROJECT_BRIEF.md](docs/AI_PROJECT_BRIEF.md) for roadmap.
