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

## Hook templates (V1 — `brainkm/hooks/cursor/`)

### SessionStart

Inject frozen brain pack (pinned + rules + context + procedures).

### SessionEnd

Run capture pipeline: distill transcript → neurons + session_chunks.

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

Match `write`, `edit`, `run_terminal` → optional `context_pack`.

### PostToolUse

Match `Write|Edit` → touch `.brain/graph_sync.requested` for debounced MCP background graph sync (no extract in hook).

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

## bench suites (V1.5)

| Suite | Fixtures | Metric |
|-------|----------|--------|
| token | 10 queries | tokens saved vs file-read |
| dmr | 5 multi-session | recall@1 vs summarize baseline |
| longmem | 10 questions (2 per ability) | accuracy + abstention rate |

## Windows notes

- Use `pathlib` for all paths (transcripts, `.brain/`, plans glob).
- Hook commands must use absolute path to `brainkm` binary.
- Document transcript path differences in install output.
