---
name: memnetwork-backend
description: >-
  Build and modify the MemNetwork brainkm package: MCP server, SQLite brain,
  Graphify adapter, hooks, CLI, Pydantic config, pytest. Use when working on
  Python files under brainkm/, MCP tools, services, adapters, or tests.
---

# MemNetwork Backend Development

Guide for implementing features in the **brainkm** Python package.
Current version: **0.5.0** (keep in lockstep with `pyproject.toml` and `__version__` — see the release checklist in `AGENTS.md`). Feature history lives in the Implementation status table of `docs/AI_PROJECT_BRIEF.md`; do not re-derive it here.

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
| `brainkm/brainkm/server.py` | MCP stdio/HTTP; `TOOL_DEFINITIONS` (name, description, request, response) |
| `brainkm/brainkm/tools/dispatch.py` | All MCP handlers (`handle_<tool>`) + `dispatch_tool` router |
| `brainkm/brainkm/config.py` | `get_settings()` env config |
| `brainkm/brainkm/models/brain_config.py` | `.brain/config.json` schema |
| `brainkm/brainkm/models/schemas.py` | MCP tool I/O models |
| `brainkm/brainkm/services/` | Business logic — memory, recall, search, budget, snapshot, learning, procedures, review, write_queue, mcp_results, … |
| `brainkm/brainkm/adapters/` | graphify, transcripts, redaction, distill (rules/cursor/claude/antigravity/ollama/groq), embeddings/onnx |
| `brainkm/brainkm/hooks/cursor/` | Installed hook + rule templates (`hooks.json`, `brainkm.mdc`) |
| `brainkm/brainkm/hooks/claude/` | Claude Code settings hooks template, rules, routing skill |
| `brainkm/brainkm/hooks/antigravity/` | Antigravity `.agents/` hooks, rules, routing skill (`serverUrl` HTTP) |
| `brainkm/brainkm/services/client_adapters.py` | Cursor / Claude / Antigravity / generic install adapters |
| `brainkm/brainkm/tui/` | Optional Textual `brainkm configure` (app checkboxes, Start Brain, Semantic Quality consent) |
| `brainkm/brainkm/db/` | SQLite connection (WAL), migrations, FTS5 |
| `brainkm/tests/` | pytest suite (`tests/tui/` holds Textual snapshot tests) |
| `.venv/` | Python venv at repo root |
| `docs/AI_PROJECT_BRIEF.md` | Product + architecture brief, implementation status |
| `docs/CLI_COMMANDS.md` | Full CLI command catalog |
| `docs/TUI_APP_PLAN.md` | Shipped `brainkm configure` Textual app (design + post-build notes) |

## Architecture (mandatory)

```
MCP Tool → Service → Adapter → SQLite
```

- Handlers stay thin — no SQL or file I/O directly; delegate to `services/` (SQL helpers live in `services/mcp_results.py`).
- Every DB-touching MCP handler runs through the single-writer `WriteQueue` (`_run_write` in `dispatch.py`) — never open ad-hoc write connections from a handler.
- Services own business logic and token budget enforcement (1500-token cap on agent-facing packs).
- Adapters wrap Graphify, transcript JSONL, plan files, redaction.
- Settings via `get_settings()` — never `os.environ` in app code.

Read `.cursor/rules/memnetwork-architecture.mdc` for full rules.

## Local dev

```bash
bash brainkm/scripts/setup_dev.sh
source .venv/bin/activate
pip install -e "./brainkm[tui]"   # optional
# brainkm configure  # guided multi-client / shared brain
pytest
brainkm version
```

Python **3.11 or 3.12** recommended.

## Adding an MCP tool

1. Define request/response models in `models/schemas.py`
2. Implement the logic as a service function in `services/` (testable without MCP transport)
3. Add `handle_<name>(conn, request, ...)` in `tools/dispatch.py` and route it in `dispatch_tool` via `_run_write` (WriteQueue)
4. Register `(name, description, RequestModel, ResponseModel)` in `TOOL_DEFINITIONS` in `server.py`
5. Add tests in `tests/` (see `test_mcp_tools.py` for handler-level patterns)
6. Update the tool tables in `docs/AI_PROJECT_BRIEF.md` §4 and `.cursor/rules/memnetwork-mcp-tools.mdc`

## Invariants (do not regress)

- **Token budget** — `budget.total_tokens` (default 1500) enforced end-to-end on agent-facing MCP payloads and the SessionStart snapshot; lean `context_pack` by default (`include_structured` opt-in)
- **Capture** — hooks + `auto_observe` fill the brain; MCP `remember` descriptions/docs stay pin/correct (do not re-promote as the everyday store path)
- **Redaction** — every neuron write path (MCP `remember`, observe, capture, handover, plan ingest, import, supersede) funnels through `remember_neuron`, which redacts and injection-scans
- **Abstention** — `recall` returns `[]` on low confidence (percentile default P10); max 3 recalls/turn
- **Soft delete only** — `forget` sets `valid_until`; hard delete is a `brainkm repair` admin path

## Security

- Never bypass `remember_neuron` when writing neurons — it is the redaction/injection-scan chokepoint (`adapters/redaction.py`)
- Never log neuron bodies at INFO — use DEBUG with redaction
- See `.cursor/rules/memnetwork-security.mdc`

## Reference

See [reference.md](reference.md) for hook templates, neuron subtypes, learning/review, and bench suites.
