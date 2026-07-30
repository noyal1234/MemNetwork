# Installing MemNetwork / brainkm

Clone this repo on a new machine and run brainkm as an MCP server for your coding IDE(s).

**License:** Apache-2.0 — [LICENSE](../LICENSE), [NOTICE](../NOTICE). Copyright © 2026 Noyal Bastin Benny. Contributions: [CONTRIBUTING.md](../CONTRIBUTING.md) + [CLA.md](../CLA.md).

**Public install:** PyPI / `uvx` one-liner is deferred until the repository is public and the installable package name is finalized. Until then, use the clone + editable install below. See [PUBLIC_RELEASE_CHECKLIST.md](PUBLIC_RELEASE_CHECKLIST.md).

## Per-host guides

Each IDE has different MCP paths, hook events, and trust quirks. Pick yours:

| Host | Guide | Exclusive highlights |
|------|-------|----------------------|
| **Cursor** | [install/cursor.md](install/cursor.md) | PreCompact + SessionEnd; `.cursor/mcp.json` + `brainkm.mdc` |
| **Google Antigravity** | [install/antigravity.md](install/antigravity.md) | `.agents/` + `serverUrl`; Stop → project `.brain/` (`--project-dir` bake) |
| **Claude Code** | [install/claude-code.md](install/claude-code.md) | Hooks in `.claude/settings.json`; Subagent + PostCompact |
| **OpenAI Codex** | [install/codex.md](install/codex.md) | `.codex/config.toml`; trust project + `/hooks`; Stop → session-end |
| **Generic MCP** | [install/generic.md](install/generic.md) | No hooks — manual `capture` / `handover` |

Same `.brain/brain.db` across all hosts. Multi-app: `brainkm configure` → **Start Brain**.

## Prerequisites

- Python **3.11 or 3.12** (`requires-python = ">=3.11"` in `brainkm/pyproject.toml`)
- At least one supported host (Cursor ~0.46+ for PreCompact, Claude Code, Antigravity, Codex CLI, or any MCP client)

## Clone and setup

```bash
git clone <your-remote-url> MemNetwork
cd MemNetwork

bash brainkm/scripts/setup_dev.sh
source .venv/bin/activate
brainkm install --dev
brainkm graph sync          # optional: first code graph
brainkm graph status
pytest
brainkm version   # expect 0.9.0
```

Restart your IDE or reload MCP servers after `brainkm install --dev`.

### Optional: commit change trace

New installs default `git.commit_trace=true` and write a merge-safe `.git/hooks/post-commit` that runs `brainkm git-note` (sha→session joins; diffs stay in git). Existing projects that never set the key stay **Off** until you enable them.

```bash
# TUI: Config → Git → Commit Trace Hook → Save
brainkm configure

# Or set in .brain/config.json then reinstall:
# "git": { "commit_trace": true, "commit_retention_days": 90 }
brainkm install --dev

brainkm trace path/to/file.py   # same as MCP trace_changes
```

Dashboard **STATUS → Commit Trace** shows `on` / `off` / `on · no hook` / `skipped` (husky/lefthook/`core.hooksPath`).

### Easiest path: guided setup (recommended)

```bash
pip install -e "./brainkm[tui]"
brainkm configure
```

The wizard asks **which coding apps you use** in plain language:

- **One app** → silent memory, no extra terminal (the app starts the brain for you).
- **Two or more** → shared brain across apps; on the last screen click **Start Brain** (or use Dashboard → Start Brain). You only start it once while you work — not every chat.
- **Claude Code** → writes `.claude/settings.json` hooks + project `.mcp.json` (not `.claude/hooks.json`). Dashboard shows Claude hooks status when present.
- **Antigravity** → writes `.agents/mcp_config.json` (HTTP uses `serverUrl`) + `.agents/hooks.json` + rules/skills. Dashboard shows AGY hooks when `.agents/` is present. Installed Stop/PreInvocation commands bake absolute `--project-dir` so distill always hits the **project** `.brain/` (Antigravity often runs hooks with cwd=`.agents/`). `brainkm doctor` / PreInvocation auto-heal rewrite missing `--project-dir` and remove a leftover shadow `.agents/.brain` after merging `agy_sessions.json`.
- **Codex CLI** → writes `.codex/config.toml` (`[mcp_servers.brainkm]`), `.codex/hooks.json` (PascalCase nested schema), skill, and upserts `AGENTS.md`. **Required after install:** trust the project `.codex/` layer, then open `/hooks` and trust brainkm commands — MCP can look enabled (gear locked) while untrusted hooks are still skipped. See [install/codex.md](install/codex.md).

You do **not** need to memorize `serve` / `connect` commands.

Opens the dashboard (or first-run wizard if `.brain/` is missing). See [TUI_APP_PLAN.md](TUI_APP_PLAN.md).

### macOS: `ModuleNotFoundError: No module named 'brainkm'`

On macOS, files inside `.venv` can be marked `UF_HIDDEN`. Python 3.12+ ignores hidden editable-install `.pth` files, so the setuptools console script may stop working until the venv is repaired.

**0.8.6+:** the installed `.venv/bin/brainkm` launcher clears hidden flags on invoke, writes `.brain/cli_health.json`, and SessionStart / `brainkm doctor` surface a one-shot notice when a heal (or hard break) happened. Cursor hook exit codes alone are easy to miss.

Quick fix (no reinstall) if auto-heal is not enough:

```bash
bash brainkm/scripts/repair_venv.sh
```

Full reset:

```bash
bash brainkm/scripts/setup_dev.sh
```

`setup_dev.sh` / `repair_venv.sh` install a bootstrap launcher at `.venv/bin/brainkm` (and editable installs use `scripts/brainkm` via setuptools `script-files`, not an importlib wrapper) so the CLI and MCP server keep working even when `.pth` files are hidden. The launcher shebang is pinned to `.venv/bin/python` (and re-execs that interpreter if somehow started via system `python3`) so Cursor MCP does not need an activated shell.

### What each step does

| Step | Result |
|------|--------|
| `setup_dev.sh` | Creates `.venv` and editable `brainkm[dev,graphify]` install |
| `brainkm install --dev` | Writes `.cursor/mcp.json`, `.cursor/hooks.json`, `.cursor/rules/brainkm.mdc`, `.brain/` scaffolding |
| `brainkm install --dev --client claude` | Writes project `.mcp.json`, `.claude/settings.json` hooks (PascalCase), `.claude/rules/brainkm.md`, skill, `CLAUDE.md`; enables `auto_observe` |
| `brainkm install --dev --client antigravity` | Writes `.agents/mcp_config.json`, `.agents/hooks.json` (named `brainkm` handler), rules/skill, `AGENTS.md`; `auto_observe`; distill `antigravity` if `agy` on PATH |
| `brainkm install --dev --client codex` | Writes `.codex/config.toml` `[mcp_servers.brainkm]`, `.codex/hooks.json` (Stop → session-end), rules/skill, `AGENTS.md`; `auto_observe`; distill `codex` if `codex` on PATH |
| `brainkm graph sync` | Builds `graphify-out/graph.json` and imports into `brain.db` |

Claude Code loads hooks from **`.claude/settings.json`** only (not `.claude/hooks.json`). Verify with `brainkm doctor`.

Antigravity workspace MCP/hooks live under **`.agents/`**. HTTP shared brain uses `serverUrl` (not `url`). Optional: `brainkm connect antigravity --http --mirror-global` merges into `~/.gemini/config/mcp_config.json` when the CLI ignores workspace config. Put `GROQ_API_KEY` (and other secrets) in the **project** `.env` — AGY hook subprocesses load it via `--project-dir` even when cwd is `.agents/`.

Codex CLI reads MCP from **`.codex/config.toml`** (not JSON `mcp.json`). Project-local `.codex/` loads only when the project is trusted; hooks also need **`/hooks`** trust in the Codex UI (MCP enabled ≠ hooks running). Distill uses `capture.distill_mode: codex` (`codex exec --sandbox read-only --ask-for-approval never`) when the CLI is on PATH; otherwise install falls back to `rules`. Full trust steps: [install/codex.md](install/codex.md).

## Example vs live Cursor config

Committed templates (expected shape before install):

- [`.cursor/mcp.json.example`](../.cursor/mcp.json.example) — relative `.venv/bin/brainkm`
- [`.cursor/hooks.json.example`](../.cursor/hooks.json.example) — PATH-based `brainkm` commands

Live files (gitignored, machine-specific):

- `.cursor/mcp.json` — may use an absolute path to your venv
- `.cursor/hooks.json` — absolute `brainkm` binary from `install --dev`

You can copy examples manually, or rely on `brainkm install --dev` to create the live files.

## Committed vs gitignored

| Path | In git? | Purpose |
|------|---------|---------|
| `brainkm/` source, `tests/`, `pyproject.toml` | Yes | MCP server + CLI |
| `cursor-policy/README.md` | Yes | Notes on local Cursor policy |
| `.cursor/skills/` | Yes | Backend skill |
| `.cursor/*.example` | Yes | Config shape before install |
| `docs/`, `AGENTS.md`, `README.md` | Yes | Documentation |
| `.brain/` | No | Live brain (db, config, calibration) |
| `graphify-out/` | No | Regenerated by `brainkm graph sync` |
| `.venv/` | No | Local Python environment |
| `.cursor/rules/` | No | Policy rules + `brainkm.mdc` (local only) |
| `.cursor/mcp.json`, `.cursor/hooks.json` | No | Machine-specific paths |

## Install brainkm into another project

Use the same venv from this clone:

```bash
source /path/to/MemNetwork/.venv/bin/activate
brainkm install --dev --project-dir /path/to/other-project
```

That project gets its own `.brain/` and `.cursor/` wiring.

### Shared multi-agent brain (same machine)

Prefer `brainkm configure` in that project (check two+ apps → **Start Brain**). Power path:

```bash
brainkm install --dev --http --project-dir /path/to/other-project
# terminal 1 (or TUI Start Brain)
brainkm serve --project-dir /path/to/other-project
# wire additional clients
brainkm connect claude --http --project-dir /path/to/other-project
brainkm connect antigravity --http --project-dir /path/to/other-project
brainkm connect codex --http --hooks --project-dir /path/to/other-project
brainkm doctor --project-dir /path/to/other-project
```

For Codex: trust the project's `.codex/` layer, then open `/hooks` and trust the brainkm commands (MCP can show enabled/locked while hooks stay skipped until then).

## MCP config reference (after `install --dev`)

Stdio (default):

```json
{
  "mcpServers": {
    "brainkm": {
      "command": "<venv>/bin/brainkm",
      "args": ["mcp", "--project-dir", "."]
    }
  }
}
```

Shared HTTP (after `serve` + `connect --http`):

```json
{
  "mcpServers": {
    "brainkm": {
      "url": "http://127.0.0.1:8765/mcp/"
    }
  }
}
```

## Cursor policy rules

`memnetwork-*.mdc` rules live under `.cursor/rules/` on disk and are **not** tracked in git. See [cursor-policy/README.md](../cursor-policy/README.md).

## Maintenance

```bash
brainkm hygiene --dry-run   # list noisy auto-captured neurons
brainkm hygiene             # soft-archive them
```

Use MCP `brain_stats` for usage / abstention / dead-neuron counts. After upgrading brainkm, reload the MCP server so Cursor picks up the new tools and budget behavior.
