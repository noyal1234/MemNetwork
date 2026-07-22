# Generic MCP + brainkm

Any MCP client that can launch a stdio server or call a localhost HTTP endpoint. No IDE hooks are installed — you drive capture and compaction survival with the CLI.

**Shared brain:** same `.brain/brain.db` as first-class hosts.  
**Clone once:** [INSTALL.md](../INSTALL.md) · then wire this client.

---

## What is exclusive to generic

| Surface | Generic behavior |
|---------|------------------|
| **MCP** | Stdio: `brainkm mcp --project-dir .` · HTTP: `brainkm serve` + connect URL |
| **Hooks** | **None** — no SessionStart / SessionEnd / PreCompact automation |
| **Capture** | Manual: `brainkm capture`, `brainkm handover` |
| **Example file** | `.brain/mcp.http.example.json` after `brainkm connect generic --http` |
| **Config dir** | Uses `.brain/` for examples (no `.cursor` / `.claude` / `.agents` / `.codex` tree) |

Prefer a first-class adapter ([Cursor](cursor.md), [Claude](claude-code.md), [Antigravity](antigravity.md), [Codex](codex.md)) when the host supports hooks — silent memory is far stronger with SessionEnd + PreCompact.

---

## Install

```bash
brainkm install --dev --client generic
# Shared HTTP:
brainkm serve --project-dir .
brainkm connect generic --http
```

Point your MCP client at the stdio command or the HTTP URL (`http://127.0.0.1:8765/mcp` by default; Bearer token when enabled).

### Manual memory path

```bash
brainkm handover path/to/transcript.jsonl   # before host compaction
brainkm capture path/to/transcript.jsonl    # after a session
brainkm doctor
```

---

## Coexistence

Use brainkm MCP tools (`recall`, `context_pack`, `traverse`, …) from any compliant client. Without hooks, the brain only grows when you capture/handover or pin via `remember`.

---

## See also

- [INSTALL.md](../INSTALL.md) — clone + multi-host overview  
- [FEATURES.md](../FEATURES.md) — tool catalog  
- [Cursor](cursor.md) · [Claude Code](claude-code.md) · [Antigravity](antigravity.md) · [Codex](codex.md)
