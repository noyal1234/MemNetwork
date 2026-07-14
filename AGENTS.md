# Agent instructions — MemNetwork / brainkm

When working in this repository, read **`docs/AI_PROJECT_BRIEF.md`** first for product vision, architecture, MCP contract, Cursor coexistence, and roadmap status.

## Quick orientation

| Area | Path | Stack |
|------|------|-------|
| MCP server + CLI | `brainkm/brainkm/` | Python 3.11+, MCP SDK, Typer |
| Optional TUI | `brainkm/brainkm/tui/` | Textual (`brainkm configure`, `[tui]` extra) |
| Per-project brain | `.brain/` (target projects) | SQLite FTS5 + graph (V1) |
| Config schema | `brainkm/brainkm/models/brain_config.py` | Pydantic v2 |
| Tests | `brainkm/tests/` | pytest, pytest-asyncio |

## Rules of thumb

- **Layers:** MCP tool → service → adapter → SQLite. Never skip layers.
- **Config:** `get_settings()` for env; `BrainConfig` for `.brain/config.json`. No `os.environ` in app code.
- **Tokens:** Hard 1500-token cap on agent-facing packs (`pack_text` + compact MCP JSON; `include_structured` is opt-in).
- **Security:** Never store secrets in neurons; use `adapters/redaction.py` (V1).
- **Compaction:** Architectural truth lives in `brain.db`, not the chat window — PreCompact handover before Cursor compacts.
- **Hygiene:** Prefer `brainkm hygiene` (or injection noise gate) over injecting junk; packs are hints — always verify in source.

## Local development

```bash
bash brainkm/scripts/setup_dev.sh
source .venv/bin/activate
brainkm install --dev
pytest
brainkm version
```

Python **3.11 or 3.12** recommended. Avoid 3.14+ for now (some deps may not have wheels).

Full clone setup: [docs/INSTALL.md](docs/INSTALL.md).

## Cursor-specific assets

| Path | In git? | Purpose |
|------|---------|---------|
| `cursor-policy/README.md` | Yes | Notes on local `.cursor/rules/` (not versioned) |
| `.cursor/skills/` | Yes | Backend implementation skill |
| `.cursor/*.example` | Yes | MCP/hooks config shape before install |
| `.cursor/rules/` | No | Policy rules + `brainkm.mdc` (local only) |

Cursor rules in target projects are installed by `brainkm install` (V1).
