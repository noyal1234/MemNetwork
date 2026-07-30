# End-task A/B scorecard (uniform protocol)

## Run manifest

- **protocol_version:** `endtask_protocol/1`
- **fixture_id / version:** `endtask_v1` / `1`
- **tier:** `core`
- **host:** `cursor`
- **host_cli_version:** `cursor-sdk`
- **model:** `composer-2.5`
- **brainkm_version:** `0.9.0`
- **repo_git_sha:** `8851ebf`
- **harness_git_sha:** `8851ebf`
- **run_id:** `2026-07-30-cursor-core-8851ebf`
- **tokens_supported:** `True`
- **started_at / finished_at:** `2026-07-30T06:02:07.317544+00:00` / `2026-07-30T06:02:07.317663+00:00`
- **MCP integrity:** PARTIAL — mcp_ok 9/18 on with-arm
- **runs recorded:** 36

## Headline

| Arm | Pass | Mean tools | Mean MCP_db | mcp_ok | Mean prompt tokens |
|-----|------|------------|-------------|--------|--------------------|
| **with brainkm** | 9/18 | 12.3 | 0.5 | 9/18 | 79927 (−21% vs without) |
| without | 18/18 | 16.8 | 0.0 | 18/18 | 100749 |

## Per-run

| Task | Class | Arm | Rep | Pass | Tools | MCP_db | mcp_ok | prompt_tok | Status | Detail |
|------|-------|-----|-----|------|-------|--------|--------|------------|--------|--------|
| `k_budget_cap` | knowledge | with_brainkm | 1 | Y | 6 | 1 | Y | 70157 | `finished` | all_patterns |
| `k_budget_cap` | knowledge | with_brainkm | 2 | Y | 12 | 1 | Y | 87626 | `finished` | all_patterns |
| `k_budget_cap` | knowledge | with_brainkm | 3 | Y | 6 | 1 | Y | 61661 | `finished` | all_patterns |
| `k_budget_cap` | knowledge | without | 1 | Y | 26 | 0 | Y | 152753 | `finished` | all_patterns |
| `k_budget_cap` | knowledge | without | 2 | Y | 22 | 0 | Y | 104010 | `finished` | all_patterns |
| `k_budget_cap` | knowledge | without | 3 | Y | 20 | 0 | Y | 140422 | `finished` | all_patterns |
| `k_remember_role` | knowledge | with_brainkm | 1 | N | 4 | 0 | N | 63634 | `finished` | all_patterns; mcp_unused(MCP_db=0) |
| `k_remember_role` | knowledge | with_brainkm | 2 | Y | 4 | 1 | Y | 27316 | `finished` | all_patterns |
| `k_remember_role` | knowledge | with_brainkm | 3 | N | 6 | 0 | N | 59908 | `finished` | all_patterns; mcp_unused(MCP_db=0) |
| `k_remember_role` | knowledge | without | 1 | Y | 8 | 0 | Y | 55636 | `finished` | all_patterns |
| `k_remember_role` | knowledge | without | 2 | Y | 14 | 0 | Y | 75996 | `finished` | all_patterns |
| `k_remember_role` | knowledge | without | 3 | Y | 10 | 0 | Y | 60650 | `finished` | all_patterns |
| `k_fusion_mode` | knowledge | with_brainkm | 1 | Y | 26 | 1 | Y | 145556 | `finished` | all_patterns |
| `k_fusion_mode` | knowledge | with_brainkm | 2 | Y | 26 | 1 | Y | 146854 | `finished` | all_patterns |
| `k_fusion_mode` | knowledge | with_brainkm | 3 | Y | 28 | 1 | Y | 151812 | `finished` | all_patterns |
| `k_fusion_mode` | knowledge | without | 1 | Y | 30 | 0 | Y | 163273 | `finished` | all_patterns |
| `k_fusion_mode` | knowledge | without | 2 | Y | 28 | 0 | Y | 225769 | `finished` | all_patterns |
| `k_fusion_mode` | knowledge | without | 3 | Y | 26 | 0 | Y | 158459 | `finished` | all_patterns |
| `k_layers` | knowledge | with_brainkm | 1 | Y | 18 | 1 | Y | 104716 | `finished` | all_patterns |
| `k_layers` | knowledge | with_brainkm | 2 | N | 36 | 0 | N | 156930 | `finished` | all_patterns; mcp_unused(MCP_db=0) |
| `k_layers` | knowledge | with_brainkm | 3 | Y | 20 | 1 | Y | 119782 | `finished` | all_patterns |
| `k_layers` | knowledge | without | 1 | Y | 26 | 0 | Y | 115744 | `finished` | all_patterns |
| `k_layers` | knowledge | without | 2 | Y | 28 | 0 | Y | 125967 | `finished` | all_patterns |
| `k_layers` | knowledge | without | 3 | Y | 26 | 0 | Y | 165053 | `finished` | all_patterns |
| `c_budget_default` | change | with_brainkm | 1 | N | 4 | 0 | N | 33195 | `finished` | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000); mcp_unused(MCP_db=0) |
| `c_budget_default` | change | with_brainkm | 2 | N | 4 | 0 | N | 33194 | `finished` | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000); mcp_unused(MCP_db=0) |
| `c_budget_default` | change | with_brainkm | 3 | N | 4 | 0 | N | 33201 | `finished` | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000); mcp_unused(MCP_db=0) |
| `c_budget_default` | change | without | 1 | Y | 4 | 0 | Y | 31878 | `finished` | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000) |
| `c_budget_default` | change | without | 2 | Y | 4 | 0 | Y | 27316 | `finished` | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000) |
| `c_budget_default` | change | without | 3 | Y | 4 | 0 | Y | 31888 | `finished` | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000) |
| `c_endtask_fixture_present` | change | with_brainkm | 1 | N | 6 | 0 | N | 47679 | `finished` | 2:  "id": "endtask_v1",; mcp_unused(MCP_db=0) |
| `c_endtask_fixture_present` | change | with_brainkm | 2 | N | 6 | 0 | N | 47692 | `finished` | 2:  "id": "endtask_v1",; mcp_unused(MCP_db=0) |
| `c_endtask_fixture_present` | change | with_brainkm | 3 | N | 6 | 0 | N | 47776 | `finished` | 2:  "id": "endtask_v1",; mcp_unused(MCP_db=0) |
| `c_endtask_fixture_present` | change | without | 1 | Y | 10 | 0 | Y | 60770 | `finished` | 2:  "id": "endtask_v1", |
| `c_endtask_fixture_present` | change | without | 2 | Y | 10 | 0 | Y | 72170 | `finished` | 2:  "id": "endtask_v1", |
| `c_endtask_fixture_present` | change | without | 3 | Y | 6 | 0 | Y | 45735 | `finished` | 2:  "id": "endtask_v1", |

## Notes

- backend=cursor
- protocol=endtask_protocol/1
- tier=core
- repeats=3
- tokens_source=host_usage when SDK returns usage
- Nondeterministic — re-run with --repeats 3 before publishing claims.
- backend=cursor
- protocol=endtask_protocol/1
- tier=core
- repeats=3
- tokens_source=host_usage when SDK returns usage
- Nondeterministic — re-run with --repeats 3 before publishing claims.
