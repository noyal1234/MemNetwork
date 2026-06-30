---
name: memnetwork-backend
description: >-
  Build and modify the MemNetwork brainkm package: MCP server, SQLite brain,
  Graphify adapter, hooks, CLI, Pydantic config, pytest. Use when working on
  Python files under brainkm/, MCP tools, services, adapters, or tests.
---

# MemNetwork Backend Development

Guide for implementing features in the **brainkm** Python package.

## When to use this skill

- Creating or editing Python under `brainkm/brainkm/`
- Adding MCP tools, services, adapters, or DB migrations
- Changing `BrainConfig` or MCP tool schemas
- Writing pytest tests
- Running local dev (`setup_dev.sh`, pytest, `brainkm` CLI)

## Project paths

| Path | Purpose |
|------|---------|
| `brainkm/brainkm/cli.py` | Typer CLI entry |
| `brainkm/brainkm/config.py` | `get_settings()` env config |
| `brainkm/brainkm/models/brain_config.py` | `.brain/config.json` schema |
| `brainkm/brainkm/models/schemas.py` | MCP tool I/O models |
| `brainkm/brainkm/tools/` | Thin MCP handlers |
| `brainkm/brainkm/services/` | memory, search, budget, snapshot |
| `brainkm/brainkm/adapters/` | graphify, transcripts, redaction |
| `brainkm/brainkm/db/` | SQLite, migrations, FTS5 |
| `brainkm/tests/` | pytest suite |
| `.venv/` | Python venv at repo root |
| `docs/AI_PROJECT_BRIEF.md` | Product + architecture brief |

## Architecture (mandatory)

```
MCP Tool → Service → Adapter → SQLite
```

- Tools stay thin — no SQL or file I/O directly.
- Services own business logic and token budget enforcement.
- Adapters wrap Graphify, transcript JSONL, plan files, redaction.
- Settings via `get_settings()` — never `os.environ` in app code.

Read `.cursor/rules/memnetwork-architecture.mdc` for full rules.

## Local dev

```bash
bash brainkm/scripts/setup_dev.sh
source .venv/bin/activate
pytest
brainkm version
```

Python **3.11 or 3.12** recommended.

## V1 implementation order

1. **DB** — schema, migrations, WAL, FTS5 (`db/`)
2. **BrainConfig loader** — read `.brain/config.json` on startup
3. **Services** — memory, search (BM25), budget (tiktoken)
4. **MCP tools** — remember, recall, context_pack, context, traverse, forget
5. **Adapters** — transcripts, plans, graphify, redaction
6. **Hooks** — SessionStart/End, PreCompact handover, PreToolUse
7. **CLI** — install, export, handover, migrate

## Adding an MCP tool

1. Define request/response in `models/schemas.py`
2. Implement service method in `services/`
3. Add thin handler in `tools/<name>.py`
4. Register in `server.py` (V1)
5. Add pytest in `tests/`

## Security

- Run all `remember` and capture input through `adapters/redaction.py` (V1)
- Never log neuron bodies at INFO — use DEBUG with redaction
- See `.cursor/rules/memnetwork-security.mdc`

## Reference

See [reference.md](reference.md) for hook JSON templates, neuron subtypes, and bench fixtures.
