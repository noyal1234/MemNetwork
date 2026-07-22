# End-task A/B scorecard (uniform protocol)

## Run manifest

- **protocol_version:** `endtask_protocol/1`
- **fixture_id / version:** `endtask_v1` / `1`
- **tier:** `core`
- **host:** `antigravity`
- **host_cli_version:** `agy`
- **model:** `agy-default`
- **brainkm_version:** `0.8.1`
- **repo_git_sha:** `20df13c`
- **harness_git_sha:** `20df13c`
- **run_id:** `2026-07-22-antigravity-core-20df13c`
- **tokens_supported:** `False`
- **started_at / finished_at:** `2026-07-22T09:48:09.284931+00:00` / `2026-07-22T10:29:59.130314+00:00`
- **MCP integrity:** ok
- **runs recorded:** 36

## Headline

| Arm | Pass | Mean tools | Mean MCP_db | mcp_ok | Mean prompt tokens |
|-----|------|------------|-------------|--------|--------------------|
| **with brainkm** | 18/18 | 15.2 | 1.7 | 18/18 | N/A |
| without | 12/18 | 16.1 | 0.0 | 18/18 | N/A |

> **Tokens:** N/A on this host (`tokens_source=unavailable`). Do not invent session token reduction from prompt/final-answer estimates.

## Per-run

| Task | Class | Arm | Rep | Pass | Tools | MCP_db | mcp_ok | prompt_tok | Status | Detail |
|------|-------|-----|-----|------|-------|--------|--------|------------|--------|--------|
| `k_budget_cap` | knowledge | with_brainkm | 1 | Y | 9 | 2 | Y | N/A | `finished` | all_patterns |
| `k_budget_cap` | knowledge | with_brainkm | 2 | Y | 9 | 3 | Y | N/A | `finished` | all_patterns |
| `k_budget_cap` | knowledge | with_brainkm | 3 | Y | 8 | 2 | Y | N/A | `finished` | all_patterns |
| `k_budget_cap` | knowledge | without | 1 | Y | 29 | 0 | Y | N/A | `finished` | all_patterns |
| `k_budget_cap` | knowledge | without | 2 | Y | 37 | 0 | Y | N/A | `finished` | all_patterns |
| `k_budget_cap` | knowledge | without | 3 | Y | 20 | 0 | Y | N/A | `finished` | all_patterns |
| `k_remember_role` | knowledge | with_brainkm | 1 | Y | 5 | 1 | Y | N/A | `finished` | all_patterns |
| `k_remember_role` | knowledge | with_brainkm | 2 | Y | 4 | 1 | Y | N/A | `finished` | all_patterns |
| `k_remember_role` | knowledge | with_brainkm | 3 | Y | 7 | 1 | Y | N/A | `finished` | all_patterns |
| `k_remember_role` | knowledge | without | 1 | Y | 4 | 0 | Y | N/A | `finished` | all_patterns |
| `k_remember_role` | knowledge | without | 2 | N | 1 | 0 | Y | N/A | `finished` | missing=['(?i)pin'] |
| `k_remember_role` | knowledge | without | 3 | N | 2 | 0 | Y | N/A | `finished` | missing=['(?i)pin'] |
| `k_fusion_mode` | knowledge | with_brainkm | 1 | Y | 27 | 2 | Y | N/A | `finished` | all_patterns |
| `k_fusion_mode` | knowledge | with_brainkm | 2 | Y | 18 | 2 | Y | N/A | `finished` | all_patterns |
| `k_fusion_mode` | knowledge | with_brainkm | 3 | Y | 40 | 2 | Y | N/A | `finished` | all_patterns |
| `k_fusion_mode` | knowledge | without | 1 | N | 24 | 0 | Y | N/A | `finished` | missing=['fts_primary'] |
| `k_fusion_mode` | knowledge | without | 2 | N | 34 | 0 | Y | N/A | `finished` | missing=['fts_primary'] |
| `k_fusion_mode` | knowledge | without | 3 | N | 24 | 0 | Y | N/A | `finished` | missing=['fts_primary'] |
| `k_layers` | knowledge | with_brainkm | 1 | Y | 6 | 2 | Y | N/A | `finished` | all_patterns |
| `k_layers` | knowledge | with_brainkm | 2 | Y | 6 | 2 | Y | N/A | `finished` | all_patterns |
| `k_layers` | knowledge | with_brainkm | 3 | Y | 8 | 2 | Y | N/A | `finished` | all_patterns |
| `k_layers` | knowledge | without | 1 | Y | 20 | 0 | Y | N/A | `finished` | all_patterns |
| `k_layers` | knowledge | without | 2 | Y | 10 | 0 | Y | N/A | `finished` | all_patterns |
| `k_layers` | knowledge | without | 3 | N | 14 | 0 | Y | N/A | `finished` | missing=['(?i)MCP', '(?i)service', '(?i)(adapter\|SQLite)'] |
| `c_budget_default` | change | with_brainkm | 1 | Y | 21 | 2 | Y | N/A | `finished` | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000) |
| `c_budget_default` | change | with_brainkm | 2 | Y | 23 | 1 | Y | N/A | `finished` | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000) |
| `c_budget_default` | change | with_brainkm | 3 | Y | 33 | 2 | Y | N/A | `finished` | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000) |
| `c_budget_default` | change | without | 1 | Y | 18 | 0 | Y | N/A | `finished` | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000) |
| `c_budget_default` | change | without | 2 | Y | 7 | 0 | Y | N/A | `finished` | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000) |
| `c_budget_default` | change | without | 3 | Y | 20 | 0 | Y | N/A | `finished` | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000) |
| `c_endtask_fixture_present` | change | with_brainkm | 1 | Y | 18 | 1 | Y | N/A | `finished` | 2:  "id": "endtask_v1", |
| `c_endtask_fixture_present` | change | with_brainkm | 2 | Y | 15 | 1 | Y | N/A | `finished` | 2:  "id": "endtask_v1", |
| `c_endtask_fixture_present` | change | with_brainkm | 3 | Y | 16 | 1 | Y | N/A | `finished` | 2:  "id": "endtask_v1", |
| `c_endtask_fixture_present` | change | without | 1 | Y | 16 | 0 | Y | N/A | `finished` | 2:  "id": "endtask_v1", |
| `c_endtask_fixture_present` | change | without | 2 | Y | 4 | 0 | Y | N/A | `finished` | 2:  "id": "endtask_v1", |
| `c_endtask_fixture_present` | change | without | 3 | Y | 6 | 0 | Y | N/A | `finished` | 2:  "id": "endtask_v1", |

## Notes

- protocol=endtask_protocol/1
- tier=core
- host=antigravity; tokens_supported=false
- MCP via session_activity; prefer --home-mcp-swap
- print-timeout=5m
- home-mcp-swap enabled
- require-mcp enabled
- protocol=endtask_protocol/1
- tier=core
- host=antigravity; tokens_supported=false
- MCP via session_activity; prefer --home-mcp-swap
- print-timeout=5m
- home-mcp-swap enabled
- require-mcp enabled
