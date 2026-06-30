# Cursor policy (MemNetwork)

MemNetwork Cursor policy rules (`memnetwork-*.mdc`) and install output (`brainkm.mdc`) live under **`.cursor/rules/`** on disk.

That directory is **gitignored** for now — policy rules are not versioned in this repository.

After clone, run `brainkm install --dev` to add `brainkm.mdc`, MCP config, hooks, and `.brain/` scaffolding. Add or restore `memnetwork-*.mdc` rules locally under `.cursor/rules/` as needed for your machine.
