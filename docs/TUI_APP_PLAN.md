# Plan: `brainkm configure` Textual TUI

**Status:** Design only — no `brainkm/brainkm/tui/` implementation in this pass.  
**Goal:** A full-screen terminal app that helps users configure and operate the project brain with live status panels, forms, and action buttons.

## Motivation

Today configuration is JSON + scattered CLI commands (`ollama doctor`, `groq doctor`, `graph status`, `review list`, …). A Textual dashboard keeps the same service layer while giving a guided, visual workflow.

## Entry point

```bash
pip install -e "./brainkm[tui]"   # proposed extra: textual>=0.60.0
brainkm configure [--project-dir PATH]
```

- New Typer command `configure` in `brainkm/cli.py` launches `textual.App`.
- New optional dependency group in `pyproject.toml`:

```toml
tui = ["textual>=0.60.0"]
```

## Architecture (mandatory layering)

```
brainkm configure (CLI)
  → brainkm.tui.app.BrainkmConfigureApp (Textual)
    → services/* (in-process)
      → adapters / db
```

**Do not** shell out to `brainkm …` subprocesses. Call existing services directly:

| UI need | Service / helper |
|---------|------------------|
| Hardware / Ollama status | `build_doctor_report`, `apply_recommended_model` |
| Groq status | `build_groq_report` |
| Config load/save | `load_brain_config`, `config_path`, JSON write helper (same pattern as `apply_recommended_model`) |
| Graph status / sync | `build_graph_status`, `sync_graph` |
| Review queue | `list_pending`, `approve_pending`, `reject_pending` |
| Bench | `run_bench_suite`, `format_suite_result` |

## Command enumeration

- **Live menu tree:** introspect `brainkm.cli.app` (Typer → Click) so the TUI never lists a command that does not exist.
- **Display metadata only:** category labels and short blurbs from [CLI_COMMANDS.md](CLI_COMMANDS.md) (Setup, Capture, LLM diagnostics, Graph, Review, Bench, Data, Viz/Server). Do **not** parse the markdown as the source of truth for which commands exist.

## Proposed package layout

```
brainkm/brainkm/tui/
  __init__.py
  app.py                 # BrainkmConfigureApp
  screens/
    dashboard.py
    config_editor.py
    actions.py
    wizard.py
  widgets/
    status_panel.py
    rich_log_panel.py
```

## Phased screens

### Phase 1 — Dashboard (read-only)

- `capture.distill_mode`
- Ollama reachable + recommended vs configured model
- Groq API key present (masked) + reachable
- Graph stale / node count
- Pending review count
- Keyboard: `q` quit, `c` config, `a` actions, `w` wizard

### Phase 2 — Config editor

Form screens writing `.brain/config.json`:

- `capture.distill_mode` (`rules` / `cursor` / `ollama` / `groq`)
- `ollama.*` (model, auto_select_model, timeout, base_url)
- `groq.*` (model, timeout, base_url) — **not** the API key
- `budget.*` (total_tokens and slot budgets)

API key entry writes to project `.env` as `GROQ_API_KEY=…` (never into config JSON or neurons).

### Phase 3 — Action panels

Buttons that invoke services and stream results into a `RichLog`:

- `graph sync` / `graph status`
- `bench run <suite>`
- `review approve` / `reject` (select from pending list)
- `ollama doctor --apply` equivalent
- `groq doctor` refresh

### Phase 4 — First-run wizard

Guided alternative to manual `brainkm install` + doctor commands:

1. Confirm project dir / run install scaffolding if missing
2. Hardware doctor → recommend Ollama model (optional apply)
3. Offer Groq path → paste API key into `.env`
4. Set `distill_mode`
5. Optional first `graph sync`

## Non-goals (this design pass)

- Implementing Textual screens or the `configure` command
- Replacing Cursor hooks or MCP tools
- Cloud vector DBs or multi-tenant auth

## Acceptance criteria (when implemented later)

- [ ] `brainkm configure` launches without crashing when `textual` is installed
- [ ] Missing `textual` prints a clear `pip install -e "./brainkm[tui]"` hint
- [ ] Dashboard reflects live Ollama/Groq/graph/review status
- [ ] Config edits validate via `BrainConfig` before write
- [ ] No secrets written to `.brain/config.json` or `brain.db`
- [ ] Menu categories stay aligned with [CLI_COMMANDS.md](CLI_COMMANDS.md); command list comes from Typer introspection
