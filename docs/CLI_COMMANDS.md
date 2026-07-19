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
| `brainkm install` | Scaffold `.brain/`, MCP config, hooks, rule | `--project-dir`, `--dev`, `--force`, `--no-graph`, `--client cursor\|claude\|antigravity\|codex\|generic`, `--http`, `--host`, `--port` | `brainkm install --dev --client antigravity` |
| `brainkm serve` | Shared HTTP MCP server (alias of `mcp --http`) | `--project-dir`, `--host`, `--port`, `--allow-remote` | `brainkm serve --project-dir .` |
| `brainkm connect` | Wire a client to stdio or shared HTTP (writes Bearer token into client MCP config) | `--project-dir`, `--http/--stdio`, `--hooks/--no-hooks`, `--host`, `--port`, `--dev`, `--mirror-global` (Antigravity) | `brainkm connect antigravity --http` |
| `brainkm doctor` | Health + client wiring + auto_observe / dual-writer / missing Bearer checks | `--project-dir`, `--host`, `--port` | `brainkm doctor` |
| `brainkm migrate` | Apply pending SQLite migrations | `--project-dir` | `brainkm migrate` |
| `brainkm configure` | Launch Textual config dashboard (wizard / status / forms / actions) | `--project-dir` | `brainkm configure` |

> **Tip:** Prefer `brainkm configure` (0.5.0): app checkboxes (Cursor / Claude / Antigravity / Codex) → one app = silent stdio; two+ = shared HTTP + **Start Brain**. Semantic Quality consent is separate. Power users: `serve` + `connect --http`. Requires `pip install -e "./brainkm[tui]"`. Semantic weights: `pip install -e "./brainkm[semantic]"`. Design notes: [TUI_APP_PLAN.md](TUI_APP_PLAN.md).
>
> **Dashboard:** the **MCP Doctor** panel shows the same wiring report as `brainkm doctor` (color-coded). **Review Queue** lists low-confidence auto-captures for `y` approve / `n` reject.

---

## Capture & distill

| Command | Purpose | Key flags | Example |
|---------|---------|-----------|---------|
| `brainkm capture` | Ingest transcript JSONL → chunks + distilled neurons | `--project-dir`, `--session-id` | `brainkm capture path/to/transcript.jsonl` |
| `brainkm handover` | PreCompact durable distill + WAL checkpoint | `--project-dir`, `--session-id`, `--stdin` | `brainkm handover --stdin` |

Distill backend is selected by `capture.distill_mode` in `.brain/config.json`: `rules` \| `cursor` \| `claude` \| `antigravity` \| `ollama` \| `groq` (legacy `mcp` coerces to `claude`).

**Groq (cloud):** also set `capture.cloud_distill_acknowledged: true` (wizard sets this when you pick groq). Without consent, Groq mode falls back to `rules` and never uploads transcripts.

All modes clean host chrome before extract. PreCompact / synthetic-precompact handover allows up to `handover.precompact_distill_timeout_seconds` (default **30s**) before falling back to `rules`. `claude` uses live MCP sampling when registered, else `claude -p`; `antigravity` uses `agy -p`.

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
| `brainkm hygiene` | Soft-archive noisy (and optionally decayed) neurons; sweeps observation TTL | `--project-dir`, `--dry-run`, `--limit`, `--decay`, `--unused-days` | `brainkm hygiene --decay` |
| `brainkm consolidate` | Merge near-duplicate neurons (sleep-time pass) | `--project-dir`, `--dry-run`, `--limit`, `--llm` | `brainkm consolidate --llm` |
| `brainkm provenance` | Print provenance chain for a node | `node_id`, `--project-dir` | `brainkm provenance <id>` |
| `brainkm file-history` | Memories linked to a code path via about_file/about_symbol | `path`, `--project-dir`, `--limit` | `brainkm file-history src/auth.py` |
| `brainkm demo` | Alias for `brainkm viz --demo` | `--project-dir`, `--port`, `--no-open` | `brainkm demo` |

Safe to re-run; archives via `forget` (reversible with audit log). SessionStart/context packs also skip noisy neurons at injection time.

---

## Bench

| Command | Purpose | Key flags | Example |
|---------|---------|-----------|---------|
| `brainkm bench run` | Run suite: `eval\|retrieval\|task\|abstention\|token\|dmr\|longmem\|budget\|compaction\|latency\|compare\|scorecard\|cma\|longmemeval` | `--project-dir`, `--live` (token), `--profile` (latency/eval), `--fixture-only` (task), `--judge` (task), `--write-scorecard` (cma), `--dataset`/`--stratify`/`--semantic` (longmemeval) | `brainkm bench run cma` |
| `brainkm bench probe` | Live `context_pack` size for one query | `--project-dir`, `--baseline` | `brainkm bench probe "how does token budget greedy truncation work" --baseline brainkm/brainkm/services/budget.py` |
| `brainkm bench calibrate` | Calibrate recall abstention thresholds | `--project-dir`, `--reference`, `--seed-reference-corpus` | `brainkm bench calibrate` |

---

## Data

| Command | Purpose | Key flags | Example |
|---------|---------|-----------|---------|
| `brainkm export` | Export neurons to markdown under `.brain/exports/` | `--project-dir`, `--full`, `--output` | `brainkm export` |
| `brainkm import` | Merge or replace neurons from JSON export | `--project-dir`, `--replace` | `brainkm import export.json --replace` |
| `brainkm team-export` | Export curated neurons to `.brain/team/neurons.json` | `--project-dir` | `brainkm team-export` |
| `brainkm team-import` | Import `.brain/team/neurons.json` (confidence merge) | `--project-dir` | `brainkm team-import` |
| `brainkm repair` | Rebuild FTS5 + integrity check | `--project-dir` | `brainkm repair` |

---

## Visualization / server

| Command | Purpose | Key flags | Example |
|---------|---------|-----------|---------|
| `brainkm viz` | Launch 3D neuron graph in the browser (Neural Cosmos); opens with a per-run access token | `--project-dir`, `--port`, `--no-open`, `--demo` | `brainkm viz --port 5757` |
| `brainkm mcp` | Run MCP server (stdio or HTTP) | `--project-dir`, `--http`, `--host`, `--port`, `--allow-remote` | `brainkm mcp --http --port 8765` |

### HTTP MCP security

- Default bind is **loopback only** (`127.0.0.1`). Non-loopback hosts require `--allow-remote` or `mcp.allow_remote: true`.
- `/mcp` requires `Authorization: Bearer <token>`. Token is auto-created at `.brain/mcp_http_token` (gitignored); `connect` / `install` write it into client MCP `headers`.
- Anonymous `/health` returns `{ok, version}` only; `project_dir` is included when the Bearer token is present.
- After first `serve`, re-run `brainkm connect <client> --http` so clients pick up the token.

---

## Hooks (host-invoked; prefer not to run manually)

These commands expect hook payload JSON on stdin (`--stdin`). Cursor / Claude / Antigravity hooks call them; manual use is for debugging only.

| `--client` | Stdout envelope |
|------------|-----------------|
| `cursor` (default) | Cursor hook JSON |
| `claude` | `hookSpecificOutput` (fail-soft exit 0) |
| `antigravity` | `injectSteps` / `{decision:allow\|stop}` (pass `--event`; fail-soft) |

| Command | Host event | Purpose |
|---------|--------------|---------|
| `brainkm session-start` | SessionStart | Migrate brain.db; prepare frozen injection |
| `brainkm pre-invocation` | PreInvocation / SessionStart (AGY) | Throttled inject + synthetic precompact |
| `brainkm session-end` | SessionEnd | Capture + promote observations |
| `brainkm pre-tool` | PreToolUse | Bounded context_pack injection (AGY: allow-only) |
| `brainkm post-tool` | PostToolUse | Observations + graph sync + learning |
| `brainkm post-tool-failure` | PostToolUseFailure | Failure observation |
| `brainkm user-prompt` | UserPromptSubmit | Prompt gist observation |
| `brainkm post-compact` | PostCompact | Refresh frozen snapshot (Claude) |
| `brainkm subagent-start` | SubagentStart | Subagent activity (Claude) |
| `brainkm subagent-stop` | SubagentStop | Promote observations for subagent (Claude) |
| `brainkm agent-stop` | Stop | Claude flush / AGY idle distill (`fullyIdle`) |

Example debug:

```bash
echo '{"session_id":"debug"}' | brainkm session-start --stdin --project-dir .
echo '{"session_id":"debug"}' | brainkm session-start --stdin --client claude --project-dir .
echo '{"conversationId":"debug","invocationNum":0}' | brainkm pre-invocation --stdin --client antigravity --event PreInvocation --project-dir .
```

Install paths:

```bash
brainkm install --dev --client claude
brainkm install --dev --client antigravity
brainkm connect claude --hooks
brainkm connect antigravity --http --hooks   # optional: --mirror-global
brainkm doctor
```

---

## Related docs

- Product / architecture: [AI_PROJECT_BRIEF.md](AI_PROJECT_BRIEF.md)
- Textual configurator (`brainkm configure`): [TUI_APP_PLAN.md](TUI_APP_PLAN.md)
