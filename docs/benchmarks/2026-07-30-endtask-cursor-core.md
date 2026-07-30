# End-task A/B scorecard (uniform protocol)

## Run manifest

- **protocol_version:** `endtask_protocol/1.1`
- **fixture_id / version:** `endtask_v1` / `1`
- **tier:** `core`
- **host:** `cursor`
- **host_cli_version:** `cursor-sdk`
- **model:** `composer-2.5`
- **brainkm_version:** `0.9.0`
- **repo_git_sha:** `8851ebf`
- **harness_git_sha:** `8851ebf`
- **run_id:** `2026-07-30-cursor-core-8851ebf`
- **h2h_publish_set:** `endtask_h2h/2`
- **tokens_supported:** `True`
- **started_at / finished_at:** `2026-07-30T07:26:02.152342+00:00` / `2026-07-30T07:26:02.152542+00:00`
- **MCP integrity:** ok
- **runs recorded:** 36

## Headline

| Arm | Pass | Mean tools | Mean MCP_db | mcp_ok | Mean prompt tokens |
|-----|------|------------|-------------|--------|--------------------|
| **with brainkm** | 18/18 | 9.8 | 1.4 | 18/18 | 71115 (−30% vs without) |
| without | 17/18 | 15.7 | 0.0 | 18/18 | 102091 |

## Per-run

| Task | Class | Arm | Rep | Pass | Tools | MCP_db | mcp_ok | prompt_tok | Status | Detail |
|------|-------|-----|-----|------|-------|--------|--------|------------|--------|--------|
| `k_budget_cap` | knowledge | with_brainkm | 1 | Y | 12 | 2 | Y | 91676 | `finished` | all_patterns |
| `k_budget_cap` | knowledge | with_brainkm | 2 | Y | 12 | 2 | Y | 73120 | `finished` | all_patterns |
| `k_budget_cap` | knowledge | with_brainkm | 3 | Y | 14 | 1 | Y | 125863 | `finished` | all_patterns |
| `k_budget_cap` | knowledge | without | 1 | N | 16 | 0 | Y | 89426 | `finished` | missing=['1500'] |
| `k_budget_cap` | knowledge | without | 2 | Y | 24 | 0 | Y | 112583 | `finished` | all_patterns |
| `k_budget_cap` | knowledge | without | 3 | Y | 20 | 0 | Y | 123929 | `finished` | all_patterns |
| `k_remember_role` | knowledge | with_brainkm | 1 | Y | 4 | 1 | Y | 33715 | `finished` | all_patterns |
| `k_remember_role` | knowledge | with_brainkm | 2 | Y | 2 | 1 | Y | 33301 | `finished` | all_patterns |
| `k_remember_role` | knowledge | with_brainkm | 3 | Y | 4 | 1 | Y | 34230 | `finished` | all_patterns |
| `k_remember_role` | knowledge | without | 1 | Y | 14 | 0 | Y | 78346 | `finished` | all_patterns |
| `k_remember_role` | knowledge | without | 2 | Y | 14 | 0 | Y | 94045 | `finished` | all_patterns |
| `k_remember_role` | knowledge | without | 3 | Y | 14 | 0 | Y | 85600 | `finished` | all_patterns |
| `k_fusion_mode` | knowledge | with_brainkm | 1 | Y | 16 | 2 | Y | 97037 | `finished` | all_patterns |
| `k_fusion_mode` | knowledge | with_brainkm | 2 | Y | 14 | 2 | Y | 76415 | `finished` | all_patterns |
| `k_fusion_mode` | knowledge | with_brainkm | 3 | Y | 14 | 2 | Y | 73565 | `finished` | all_patterns |
| `k_fusion_mode` | knowledge | without | 1 | Y | 30 | 0 | Y | 199368 | `finished` | all_patterns |
| `k_fusion_mode` | knowledge | without | 2 | Y | 30 | 0 | Y | 170098 | `finished` | all_patterns |
| `k_fusion_mode` | knowledge | without | 3 | Y | 30 | 0 | Y | 223174 | `finished` | all_patterns |
| `k_layers` | knowledge | with_brainkm | 1 | Y | 10 | 2 | Y | 52193 | `finished` | all_patterns |
| `k_layers` | knowledge | with_brainkm | 2 | Y | 8 | 1 | Y | 54682 | `finished` | all_patterns |
| `k_layers` | knowledge | with_brainkm | 3 | Y | 10 | 1 | Y | 76253 | `finished` | all_patterns |
| `k_layers` | knowledge | without | 1 | Y | 20 | 0 | Y | 131446 | `finished` | all_patterns |
| `k_layers` | knowledge | without | 2 | Y | 18 | 0 | Y | 109870 | `finished` | all_patterns |
| `k_layers` | knowledge | without | 3 | Y | 26 | 0 | Y | 116659 | `finished` | all_patterns |
| `c_budget_default` | change | with_brainkm | 1 | Y | 6 | 2 | Y | 36793 | `finished` | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000) |
| `c_budget_default` | change | with_brainkm | 2 | Y | 6 | 1 | Y | 58324 | `finished` | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000) |
| `c_budget_default` | change | with_brainkm | 3 | Y | 8 | 1 | Y | 110491 | `finished` | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000) |
| `c_budget_default` | change | without | 1 | Y | 4 | 0 | Y | 31886 | `finished` | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000) |
| `c_budget_default` | change | without | 2 | Y | 4 | 0 | Y | 31886 | `finished` | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000) |
| `c_budget_default` | change | without | 3 | Y | 0 | 0 | Y | — | `error` | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000) |
| `c_endtask_fixture_present` | change | with_brainkm | 1 | Y | 12 | 1 | Y | 87758 | `finished` | 2:  "id": "endtask_v1", |
| `c_endtask_fixture_present` | change | with_brainkm | 2 | Y | 12 | 1 | Y | 77099 | `finished` | 2:  "id": "endtask_v1", |
| `c_endtask_fixture_present` | change | with_brainkm | 3 | Y | 12 | 1 | Y | 87554 | `finished` | 2:  "id": "endtask_v1", |
| `c_endtask_fixture_present` | change | without | 1 | Y | 6 | 0 | Y | 45771 | `finished` | 2:  "id": "endtask_v1", |
| `c_endtask_fixture_present` | change | without | 2 | Y | 6 | 0 | Y | 45683 | `finished` | 2:  "id": "endtask_v1", |
| `c_endtask_fixture_present` | change | without | 3 | Y | 6 | 0 | Y | 45784 | `finished` | 2:  "id": "endtask_v1", |

## Notes

- backend=cursor
- protocol=endtask_protocol/1.1
- h2h_publish_set=endtask_h2h/2
- tier=core
- repeats=3
- tokens_source=host_usage when SDK returns usage
- with-arm MCP routing: WITH_ARM_MCP_PREFIX + setting_sources=project
- Nondeterministic — re-run with --repeats 3 before publishing claims.
