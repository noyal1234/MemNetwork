# Antigravity CLI endtask A/B (Path A — live `agy --print`)

> **Generated:** 2026-07-22 08:55:28 UTC  
> **agy:** `/Users/noyal/.local/bin/agy`  
> **Method:** live CLI agent + native transcript hops + **MCP via brain.db session_activity** (not pack-vs-dump)
> **MCP integrity:** ok

## How to read this

| Column | Meaning |
|--------|---------|
| **Pass** | Soft keyword groups in the final answer (≥2 groups hit) |
| **Tools** | Native AGY hops (`VIEW_FILE`, `GREP_SEARCH`, …) from transcript |
| **MCP_db** | Rows in `.brain/brain.db` `session_activity` with `source=mcp` during the run (authoritative) |
| **mcp_ok** | with_brainkm: MCP_db≥1 (or `--require-mcp` off); without: MCP_db==0 |
| **prompt_ok** | USER_INPUT was the real TASK (not a mis-parsed CLI flag) |

Do **not** treat transcript path strings containing `brainkm/` as MCP use. If with-arm `mcp_ok` stays N, the suite is not comparable to Cursor endtask.

## Headline

- **with brainkm (all):** 8/9 pass · mean tools=32.0 · mean mcp_db=1.8 · prompt_ok=9/9 · mcp_ok=9/9
- **without:** 5/9 pass · mean tools=28.6 · mean mcp_db=0.0 · prompt_ok=9/9

## Notes

- Path A: live agy --print + native transcript hops + MCP via session_activity
- Auth: Google OAuth / plan quota (not CURSOR_API_KEY)
- print-timeout=5m
- ARGV: flags BEFORE --print (fixes prior suite where --print-timeout was the prompt)
- MCP metric: brain.db session_activity source=mcp (not transcript path false positives)
- home-mcp-swap: per-arm write/restore of ~/.gemini/config/mcp_config.json (stdio brainkm)
- require-mcp: with-arm must have MCP_db≥1; without must have MCP_db=0
- Ran with --dangerously-skip-permissions (required for headless tools)

## Per-run

| Scenario | Arm | Rep | Pass | Tools | MCP_db | mcp_ok | prompt_ok | Turns | Wall | Status | Detail |
|----------|-----|-----|------|-------|--------|--------|-----------|-------|------|--------|--------|
| `agy_arch_pivot` | with_brainkm | 1 | Y | 16 | 1 | Y | Y | 11 | 59.5s | `finished` | groups=3/2 (hit:agy, hit:rules, hit:groq) |
| `agy_arch_pivot` | with_brainkm | 2 | N | 18 | 1 | Y | Y | 13 | 363.4s | `error:exit_1:Error: timeout waiting for response` | groups=2/2 (miss:agy/print, hit:rules, hit:groq);  |
| `agy_arch_pivot` | with_brainkm | 3 | Y | 12 | 2 | Y | Y | 9 | 34.5s | `finished` | groups=3/2 (hit:agy, hit:rules, hit:groq) |
| `agy_arch_pivot` | without | 1 | Y | 5 | 0 | Y | Y | 4 | 41.3s | `finished` | groups=3/2 (hit:agy, hit:rules, hit:groq) |
| `agy_arch_pivot` | without | 2 | N | 7 | 0 | Y | Y | 6 | 126.9s | `finished` | groups=0/2 (miss:agy/print, miss:rules/RulesDistil |
| `agy_arch_pivot` | without | 3 | Y | 11 | 0 | Y | Y | 8 | 108.5s | `finished` | groups=2/2 (miss:agy/print, hit:rules, hit:groq) |
| `agy_ast_refactor` | with_brainkm | 1 | Y | 85 | 3 | Y | Y | 45 | 114.9s | `finished` | groups=3/2 (hit:hook, hit:antigravity, hit:transcr |
| `agy_ast_refactor` | with_brainkm | 2 | Y | 51 | 3 | Y | Y | 29 | 87.5s | `finished` | groups=3/2 (hit:hook, hit:antigravity, hit:transcr |
| `agy_ast_refactor` | with_brainkm | 3 | Y | 53 | 3 | Y | Y | 30 | 96.0s | `finished` | groups=3/2 (hit:hook, hit:antigravity, hit:transcr |
| `agy_ast_refactor` | without | 1 | Y | 53 | 0 | Y | Y | 28 | 98.9s | `finished` | groups=3/2 (hit:hook, hit:antigravity, hit:transcr |
| `agy_ast_refactor` | without | 2 | Y | 74 | 0 | Y | Y | 39 | 118.7s | `finished` | groups=3/2 (hit:hook, hit:antigravity, hit:transcr |
| `agy_ast_refactor` | without | 3 | Y | 57 | 0 | Y | Y | 32 | 106.7s | `finished` | groups=2/2 (hit:hook, hit:antigravity, miss:transc |
| `agy_git_join` | with_brainkm | 1 | Y | 18 | 1 | Y | Y | 11 | 37.5s | `finished` | groups=3/2 (hit:resolve_antigravity_project_dir, h |
| `agy_git_join` | with_brainkm | 2 | Y | 21 | 1 | Y | Y | 13 | 46.0s | `finished` | groups=3/2 (hit:resolve_antigravity_project_dir, h |
| `agy_git_join` | with_brainkm | 3 | Y | 14 | 1 | Y | Y | 9 | 32.0s | `finished` | groups=3/2 (hit:resolve_antigravity_project_dir, h |
| `agy_git_join` | without | 1 | N | 10 | 0 | Y | Y | 8 | 330.8s | `error:exit_1:Error: timeout waiting for response` | groups=0/2 (miss:resolve_antigravity_project_dir/p |
| `agy_git_join` | without | 2 | N | 28 | 0 | Y | Y | 18 | 185.4s | `finished` | groups=0/2 (miss:resolve_antigravity_project_dir/p |
| `agy_git_join` | without | 3 | N | 12 | 0 | Y | Y | 9 | 109.7s | `finished` | groups=1/2 (miss:resolve_antigravity_project_dir/p |

## Reproduce

```bash
export PATH="$HOME/.local/bin:$PATH"
python brainkm/scripts/antigravity_endtask_harness.py \
  --allow-skip-permissions --home-mcp-swap --require-mcp --repeats 3
```
