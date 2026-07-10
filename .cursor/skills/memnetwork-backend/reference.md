# MemNetwork backend reference

## Neuron subtypes (`kind=memory`)

| Subtype | Use |
|---------|-----|
| `fact` | Stable project fact |
| `decision` | Architectural choice ("why X not Y") |
| `pattern` | Recurring implementation pattern |
| `context` | Session/branch context |
| `rule` | Team or project rule |
| `error` | Known failure mode / anti-pattern |

## Procedure neurons (`kind=procedure`)

| Subtype | Use |
|---------|-----|
| `tool_chain` | Learned sequence of tools + recalled neurons that worked together |

Promoted automatically when co-activation edges exceed `learning.co_activation_threshold` and the session used ≥2 external tools. Source: `learning:proc:<hash>`. Included in SessionStart snapshot and `context_pack`.

## Tool nodes (`kind=tool`)

Project-scoped registry of external MCP/editor tools seen via PostToolUse. Capped at `learning.max_tool_nodes` (default 20). Idempotent by tool name.

## Hook templates (`brainkm/hooks/cursor/`)

### SessionStart

Inject frozen brain pack (pinned + rules + context + procedures).

### SessionEnd

Run capture pipeline: distill transcript → neurons + session_chunks. Low-confidence auto-captured neurons enqueue for review.

### PreCompact (`matcher: auto`)

```json
{
  "hooks": {
    "PreCompact": [{
      "matcher": "auto",
      "hooks": [{
        "type": "command",
        "command": "brainkm handover --stdin"
      }]
    }]
  }
}
```

### PreToolUse

Match `write`, `edit`, `run_terminal` (configurable via `injection.pre_tool_patterns`) → compile bounded `context_pack` and return as `additional_context`. Records neuron hits for the learning window.

### PostToolUse

On Write/Edit: touch `.brain/graph_sync.requested` for debounced MCP background graph sync (no extract in hook). On every tool use: update co-activation edges, register tool nodes, check procedure promotion.

## Learning loop (V2)

| Signal | Source | Effect |
|--------|--------|--------|
| Neuron hits | MCP `recall`, `context_pack`; PreToolUse pack | `record_neuron_hits` → session window |
| Tool use | PostToolUse hook | `record_tool_use` → tool registry |
| Co-activation | Pairs of neurons in window | `co_activated` edge weight +1 |
| Procedure | Edge weight ≥ threshold + ≥2 external tools | New `kind=procedure` neuron |

Config (`learning` in `.brain/config.json`):

| Field | Default | Meaning |
|-------|---------|---------|
| `co_activation_threshold` | 3 | Min edge weight before procedure promotion |
| `max_tool_nodes` | 20 | Cap on `kind=tool` registry |
| `auto_capture_confidence` | 0.5 | Below this → review queue on capture |
| `session_window_size` | 20 | Rolling PostToolUse/recall window |

## Review queue (V2)

Auto-captured neurons with `confidence < learning.auto_capture_confidence` land in `.brain/pending/<node_id>.json`.

```bash
brainkm review list
brainkm review approve <node_id>
brainkm review reject <node_id>   # soft-archives via forget
```

Approve sets `confidence = 1.0` and removes the pending file. Reject calls `forget` with reason `review_rejected`.

## Graphify sync commands

```bash
pip install -e "./brainkm[graphify]"   # same venv as brainkm recommended
brainkm graph sync                     # extract + import (code_only)
brainkm graph status                   # binary, staleness, node count
brainkm graph sync --skip-extract      # import-only (SessionEnd fallback uses this)
```

Troubleshooting:

- `graphify_found: false` — install `graphifyy` or set `graphify.extract_binary` to absolute path (uvx split venv).
- `graph_stale: true` — run `brainkm graph sync` after refactors or git pull.
- Empty graph after sync — check `code_only: true` and `.graphifyignore`; import refuses to wipe existing code graph on 0 nodes.

## Distill modes (local vs cloud)

| Mode | Adapter | Setup |
|------|---------|-------|
| `rules` | Rule-based (default path) | None |
| `ollama` | Local Ollama (`qwen2.5:3b` default) | `pip install -e "./brainkm[ollama]"` + `brainkm ollama doctor` |
| `groq` | Free cloud Groq (`llama-3.3-70b-versatile`) | `pip install -e "./brainkm[cloud]"` + `GROQ_API_KEY` + `brainkm groq doctor` |
| `cursor` | Cursor-side stub | Hooks only |

Set in `.brain/config.json`:

```json
{
  "capture": { "distill_mode": "groq" },
  "ollama": { "model": "qwen2.5:3b", "auto_select_model": false },
  "groq": {
    "base_url": "https://api.groq.com/openai/v1",
    "model": "llama-3.3-70b-versatile",
    "timeout_seconds": 60
  }
}
```

API keys live in env / `.env` (`GROQ_API_KEY`), never in config or neurons.

Full CLI surface: [docs/CLI_COMMANDS.md](../../../docs/CLI_COMMANDS.md).

## MCP server entry (target project)

```json
{
  "mcpServers": {
    "brainkm": {
      "command": "uvx",
      "args": ["brainkm@latest", "--project-dir", "."]
    }
  }
}
```

Local dev of brainkm:

```json
{
  "mcpServers": {
    "brainkm": {
      "command": "/path/to/MemNetwork/.venv/bin/brainkm",
      "args": ["mcp", "--project-dir", "."]
    }
  }
}
```

## Token budget slots (default)

| Slot | Tokens |
|------|--------|
| Pinned + rules | 300 |
| Context neuron | 200 |
| Active procedures | 200 |
| Graph context_pack | 500 |
| Recall results | 300 |
| **Total** | **1500** |

## Bench suites

| Suite | Fixtures | Metric |
|-------|----------|--------|
| `token` | 10 queries | tokens saved vs file-read |
| `dmr` | 5 multi-session | recall@1 vs summarize baseline |
| `longmem` | 10 questions (2 per ability) | accuracy + abstention rate |
| `abstention` | calibration fixture | pass rate vs expected recall/abstain |
| `budget` | pack profiles | token allocation per task type |
| `compaction` | 3 scenarios | neuron survival across compact cycle |

```bash
brainkm bench run token
brainkm bench run dmr
brainkm bench calibrate
```

## Windows notes

- Use `pathlib` for all paths (transcripts, `.brain/`, plans glob).
- Hook commands must use absolute path to `brainkm` binary.
- Document transcript path differences in install output.
