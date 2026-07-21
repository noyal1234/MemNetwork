# Cursor policy (MemNetwork)

MemNetwork Cursor policy rules (`memnetwork-*.mdc`) and install output (`brainkm.mdc`) live under **`.cursor/rules/`** on disk.

That directory is **gitignored** for now — policy rules are not versioned in this repository.

After clone, prefer:

```bash
pip install -e "./brainkm[tui]"
brainkm configure
```

Or `brainkm install --dev` (Cursor) / `--client claude` / `--client antigravity` to add host wiring and `.brain/` scaffolding. Add or restore `memnetwork-*.mdc` rules locally under `.cursor/rules/` as needed for your machine.

The installed host rules treat hooks as the primary memory path; MCP `remember` is pin/correct/archive only. Package version: **0.8.1**.
