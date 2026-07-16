# brainkm CLI command catalog

Authoritative human reference for every `brainkm` Typer command. The shipped `brainkm configure` TUI **introspects** `brainkm.cli.app` for the live command tree; use this file for category labels and usage notes only.

Install / activate first:

```bash
source .venv/bin/activate
pip install -e "./brainkm[dev]"   # add [ollama], [cloud], [graphify], [tui] as needed
brainkm --help
```

---

## Setup

| Command | Purpose | Key flags | Example |
|---------|---------|-----------|---------|
| `brainkm version` | Print installed package version | — | `brainkm version` |
| `brainkm install` | Scaffold `.brain/`, MCP config, hooks, rule | `--project-dir`, `--dev`, `--force`, `--no-graph`, `--client cursor\|claude\|generic` | `brainkm install --dev --client cursor` |
| `brainkm migrate` | Apply pending SQLite migrations | `--project-dir` | `brainkm migrate` |
| `brainkm configure` | Launch Textual config dashboard (wizard / status / forms / actions) | `--project-dir` | `brainkm configure` |

> **Tip:** `brainkm configure` wizard includes **Agent Client** and **Semantic Quality** consent steps (0.3.2+). Requires `pip install -e "./brainkm[tui]"`. Semantic weights: `pip install -e "./brainkm[semantic]"`. Design notes: [TUI_APP_PLAN.md](TUI_APP_PLAN.md).

---

## Capture & distill

| Command | Purpose | Key flags | Example |
|---------|---------|-----------|---------|
| `brainkm capture` | Ingest transcript JSONL → chunks + distilled neurons | `--project-dir`, `--session-id` | `brainkm capture path/to/transcript.jsonl` |
| `brainkm handover` | PreCompact durable distill + WAL checkpoint | `--project-dir`, `--session-id`, `--stdin` | `brainkm handover --stdin` |

Distill backend is selected by `capture.distill_mode` in `.brain/config.json`: `rules` \| `cursor` \| `ollama` \| `groq` \| `mcp`.

All modes clean Cursor chrome before extract. PreCompact handover allows up to `handover.precompact_distill_timeout_seconds` (default **30s**) before falling back to `rules`. `mcp` uses the host's sampling API when available.

---

## LLM diagnostics

| Command | Purpose | Key flags | Example |
|---------|---------|-----------|---------|
| `brainkm ollama doctor` | Hardware profile, recommended local model, daemon status | `--project-dir`, `--apply` | `brainkm ollama doctor --apply` |
| `brainkm semantic doctor` | Local MiniLM / CE readiness + RAM recommendation | `--project-dir` | `brainkm semantic doctor` |
| `brainkm groq doctor` | API key presence (masked), reachability, configured model | `--project-dir` | `brainkm groq doctor` |

Notes:

- Ollama default model: `qwen2.5:3b` (`pip install -e "./brainkm[ollama]"`).
- Groq default model: `llama-3.3-70b-versatile`; set `GROQ_API_KEY` (`pip install -e "./brainkm[cloud]"`).
- Never store API keys in `.brain/config.json`.

---

## Code graph

| Command | Purpose | Key flags | Example |
|---------|---------|-----------|---------|
| `brainkm graph import` | Import `graph.json` into `brain.db` | `--project-dir`, `--include-docs` | `brainkm graph import` |
| `brainkm graph sync` | Extract (optional) + import | `--project-dir`, `--skip-extract`, `--force-extract` | `brainkm graph sync` |
| `brainkm graph extract` | Run Graphify extract only | `--project-dir`, `--force` | `brainkm graph extract` |
| `brainkm graph status` | Binary, staleness, node counts, `auto_sync_enabled`, `watch_filesystem_enabled` | `--project-dir` | `brainkm graph status` |

Multi-IDE opt-in: set `graphify.auto_sync.watch_filesystem: true` in `.brain/config.json` and restart the brainkm MCP server. Filesystem events request the same sync pipeline as PostToolUse (60s debounce / 5m min interval).

---

## Review queue

| Command | Purpose | Key flags | Example |
|---------|---------|-----------|---------|
| `brainkm review list` | List low-confidence pending neurons | `--project-dir` | `brainkm review list` |
| `brainkm review approve` | Approve pending neuron (`confidence=1.0`) | `--project-dir` | `brainkm review approve <node_id>` |
| `brainkm review reject` | Reject + soft-archive via `forget` | `--project-dir` | `brainkm review reject <node_id>` |

---

## Hygiene

| Command | Purpose | Key flags | Example |
|---------|---------|-----------|---------|
| `brainkm hygiene` | Soft-archive noisy (and optionally decayed) neurons | `--project-dir`, `--dry-run`, `--limit`, `--decay`, `--unused-days` | `brainkm hygiene --decay` |
| `brainkm consolidate` | Merge near-duplicate neurons (sleep-time pass) | `--project-dir`, `--dry-run`, `--limit` | `brainkm consolidate` |

Safe to re-run; archives via `forget` (reversible with audit log). SessionStart/context packs also skip noisy neurons at injection time.

---

## Bench

| Command | Purpose | Key flags | Example |
|---------|---------|-----------|---------|
| `brainkm bench run` | Run suite: `abstention\|token\|dmr\|longmem\|budget\|compaction\|latency` | `--project-dir`, `--live` (token only) | `brainkm bench run latency` |
| `brainkm bench probe` | Live `context_pack` size for one query | `--project-dir`, `--baseline` | `brainkm bench probe "auth middleware"` |
| `brainkm bench calibrate` | Calibrate recall abstention thresholds | `--project-dir`, `--reference`, `--seed-reference-corpus` | `brainkm bench calibrate` |

---

## Data

| Command | Purpose | Key flags | Example |
|---------|---------|-----------|---------|
| `brainkm export` | Export neurons to markdown under `.brain/exports/` | `--project-dir`, `--full`, `--output` | `brainkm export` |
| `brainkm import` | Merge or replace neurons from JSON export | `--project-dir`, `--replace` | `brainkm import export.json --replace` |
| `brainkm team-export` | Export curated neurons to `.brain/team/neurons.json` | `--project-dir` | `brainkm team-export` |
| `brainkm repair` | Rebuild FTS5 + integrity check | `--project-dir` | `brainkm repair` |

---

## Visualization / server

| Command | Purpose | Key flags | Example |
|---------|---------|-----------|---------|
| `brainkm viz` | Launch 3D neuron graph in the browser | `--project-dir`, `--port`, `--no-open`, `--demo` | `brainkm viz --port 5757` |
| `brainkm mcp` | Run MCP server (stdio or HTTP) | `--project-dir`, `--http`, `--host`, `--port` | `brainkm mcp --http --port 8765` |

---

## Hooks (Cursor-invoked; prefer not to run manually)

These commands expect hook payload JSON on stdin (`--stdin`). Cursor hooks call them; manual use is for debugging only.

| Command | Cursor event | Purpose |
|---------|--------------|---------|
| `brainkm session-start` | SessionStart | Migrate brain.db; prepare frozen injection |
| `brainkm session-end` | SessionEnd | Capture transcript into neurons |
| `brainkm pre-tool` | PreToolUse | Inject bounded `context_pack` for matched tools |
| `brainkm post-compact` | PostCompact | Refresh frozen injection snapshot |
| `brainkm post-tool` | PostToolUse | Graph sync request + learning loop |

Example debug:

```bash
echo '{"session_id":"debug"}' | brainkm session-start --stdin --project-dir .
```

---

## Related docs

- Product / architecture: [AI_PROJECT_BRIEF.md](AI_PROJECT_BRIEF.md)
- Textual configurator (`brainkm configure`): [TUI_APP_PLAN.md](TUI_APP_PLAN.md)
