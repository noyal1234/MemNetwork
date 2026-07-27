# Agent instructions — MemNetwork / brainkm

When working in this repository, read **`docs/AI_PROJECT_BRIEF.md`** first for product vision, architecture, MCP contract, multi-client coexistence (Cursor / Claude / Antigravity), and roadmap status.

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
- **Capture:** Hooks + `capture.auto_observe` fill the brain; MCP `remember` is **pin/correct/archive** only (not ordinary session notes).
- **Hygiene:** Prefer `brainkm hygiene` (or injection noise gate) over injecting junk; packs are hints — always verify in source.
- **Setup:** Prefer `brainkm configure` (TUI) over memorizing `serve` / `connect`.

## Local development

```bash
bash brainkm/scripts/setup_dev.sh
source .venv/bin/activate
pip install -e "./brainkm[tui]"
brainkm configure   # or: brainkm install --dev
pytest
brainkm version
```

Python **3.11 or 3.12** recommended. Avoid 3.14+ for now (some deps may not have wheels).

Full clone setup: [docs/INSTALL.md](docs/INSTALL.md). Per-host: [docs/install/](docs/install/).

## Client install assets

| Path | In git? | Purpose |
|------|---------|---------|
| `cursor-policy/README.md` | Yes | Notes on local `.cursor/rules/` (not versioned) |
| `.cursor/skills/` | Yes | Backend implementation skill |
| `.cursor/*.example` | Yes | Cursor MCP/hooks config shape before install |
| `.cursor/rules/` | No | Policy rules + `brainkm.mdc` (local only) |
| `.cursor/hooks.json` / `.cursor/mcp.json` | No | Machine-local Cursor wiring (install output) |
| `.agents/` | No | Machine-local Antigravity wiring (install output) |
| `.codex/` | No | Machine-local Codex wiring (install output; may include HTTP bearer) |
| `.claude/` / `.mcp.json` | No | Machine-local Claude Code wiring (install output) |
| `brainkm/brainkm/hooks/cursor/` | Yes | Cursor hooks + `brainkm.mdc` + routing skill |
| `brainkm/brainkm/hooks/claude/` | Yes | Claude settings hooks, rules, routing skill |
| `brainkm/brainkm/hooks/antigravity/` | Yes | Antigravity `.agents/` hooks, rules, routing skill |
| `brainkm/brainkm/hooks/codex/` | Yes | Codex CLI hooks, rules, routing skill templates |

Client wiring is installed by `brainkm install --client …` / `brainkm configure` into the local paths above — do not commit those generated files.

## Release checklist (version bump)

When shipping a release, keep these in lockstep:

1. `brainkm/pyproject.toml` → `version`
2. `brainkm/brainkm/__init__.py` → `__version__`
3. Docs status tables / expect strings: `docs/AI_PROJECT_BRIEF.md`, `docs/INSTALL.md`, `docs/FEATURES.md`, `docs/CLI_COMMANDS.md`, `README.md`, `brainkm/README.md`, `.cursor/skills/memnetwork-backend/SKILL.md`
4. Hook/rule templates: `hooks/cursor/brainkm.mdc` (sync workspace `.cursor/rules/brainkm.mdc`), plus Claude/Antigravity/Codex rules + routing skills under `hooks/{claude,antigravity,codex}/`
5. `pytest tests/test_version.py` (asserts pyproject == `__version__`)
6. Prefer adding a brief row to the Implementation status table in `AI_PROJECT_BRIEF.md`
7. Public/PyPI first publish: follow [docs/PUBLIC_RELEASE_CHECKLIST.md](docs/PUBLIC_RELEASE_CHECKLIST.md) (installable name must be final; Apache-2.0 + CLA already in place)

# brainkm — project memory routing

Memory accumulates from **hooks** (SessionStart injection, SessionEnd distill,
PostToolUse observations). You do **not** need to call `remember` for ordinary learning.

Use the **brainkm** MCP tools:

| Question | Tool |
|----------|------|
| Why did we choose X? | `recall` |
| What calls / imports X? Impact of changing Y? | `traverse` |
| Bounded multi-file task context | `context_pack` (include a symbol or path) |
| Pin durable truth or correct a wrong auto-capture | `remember` |

Packs are hints — always verify in source before editing.
Prefer `traverse` for blast-radius; `context_pack` before opening 3+ files.
Expand truncated ids via `recall` with `truncation_followup: true`.

Installed for Antigravity via `brainkm install --client antigravity`.

## Coexistence with Antigravity native config

- **`.agents/rules` / `AGENTS.md`** = authored static instructions.
- **brainkm** = searchable project brain (decisions, graph, session survival).
- Grant `mcp(brainkm/*)` so recall/context_pack are not stuck in Ask mode.
- Do not stack Mem0 (or similar) with brainkm on the same project.
