# End-task A/B scorecard (agent with brainkm vs without)

- **fixture:** endtask_v1
- **model:** composer-2.5
- **dry_run:** True
- **runs recorded:** 40

## Headline

| Arm | Success | Mean context tokens |
|-----|---------|---------------------|
| **with brainkm** | dry-run planned n=20 | — |
| without | dry-run planned n=20 | — |

## By class

### change

- `with_brainkm`: dry-run n=8
- `without`: dry-run n=8

### knowledge

- `with_brainkm`: dry-run n=12
- `without`: dry-run n=12

## Per-run table

| Task | Class | Arm | Rep | Pass | Tokens | Wall ms | Status | Detail |
|------|-------|-----|-----|------|--------|---------|--------|--------|
| `k_budget_cap` | knowledge | with_brainkm | 1 | N | — | 0 | dry_run | dry-run |
| `k_budget_cap` | knowledge | without | 1 | N | — | 0 | dry_run | dry-run |
| `k_remember_role` | knowledge | with_brainkm | 1 | N | — | 0 | dry_run | dry-run |
| `k_remember_role` | knowledge | without | 1 | N | — | 0 | dry_run | dry-run |
| `k_fusion_mode` | knowledge | with_brainkm | 1 | N | — | 0 | dry_run | dry-run |
| `k_fusion_mode` | knowledge | without | 1 | N | — | 0 | dry_run | dry-run |
| `k_precompact` | knowledge | with_brainkm | 1 | N | — | 0 | dry_run | dry-run |
| `k_precompact` | knowledge | without | 1 | N | — | 0 | dry_run | dry-run |
| `k_layers` | knowledge | with_brainkm | 1 | N | — | 0 | dry_run | dry-run |
| `k_layers` | knowledge | without | 1 | N | — | 0 | dry_run | dry-run |
| `k_recall_budget` | knowledge | with_brainkm | 1 | N | — | 0 | dry_run | dry-run |
| `k_recall_budget` | knowledge | without | 1 | N | — | 0 | dry_run | dry-run |
| `k_dual_grain` | knowledge | with_brainkm | 1 | N | — | 0 | dry_run | dry-run |
| `k_dual_grain` | knowledge | without | 1 | N | — | 0 | dry_run | dry-run |
| `k_no_secrets` | knowledge | with_brainkm | 1 | N | — | 0 | dry_run | dry-run |
| `k_no_secrets` | knowledge | without | 1 | N | — | 0 | dry_run | dry-run |
| `k_clients` | knowledge | with_brainkm | 1 | N | — | 0 | dry_run | dry-run |
| `k_clients` | knowledge | without | 1 | N | — | 0 | dry_run | dry-run |
| `k_traverse` | knowledge | with_brainkm | 1 | N | — | 0 | dry_run | dry-run |
| `k_traverse` | knowledge | without | 1 | N | — | 0 | dry_run | dry-run |
| `k_config_env` | knowledge | with_brainkm | 1 | N | — | 0 | dry_run | dry-run |
| `k_config_env` | knowledge | without | 1 | N | — | 0 | dry_run | dry-run |
| `k_python_version` | knowledge | with_brainkm | 1 | N | — | 0 | dry_run | dry-run |
| `k_python_version` | knowledge | without | 1 | N | — | 0 | dry_run | dry-run |
| `c_ir_metrics_export` | change | with_brainkm | 1 | N | — | 0 | dry_run | dry-run |
| `c_ir_metrics_export` | change | without | 1 | N | — | 0 | dry_run | dry-run |
| `c_bench_runner_staleness` | change | with_brainkm | 1 | N | — | 0 | dry_run | dry-run |
| `c_bench_runner_staleness` | change | without | 1 | N | — | 0 | dry_run | dry-run |
| `c_fusion_mode_field` | change | with_brainkm | 1 | N | — | 0 | dry_run | dry-run |
| `c_fusion_mode_field` | change | without | 1 | N | — | 0 | dry_run | dry-run |
| `c_budget_default` | change | with_brainkm | 1 | N | — | 0 | dry_run | dry-run |
| `c_budget_default` | change | without | 1 | N | — | 0 | dry_run | dry-run |
| `c_endtask_fixture_present` | change | with_brainkm | 1 | N | — | 0 | dry_run | dry-run |
| `c_endtask_fixture_present` | change | without | 1 | N | — | 0 | dry_run | dry-run |
| `c_longmemeval_chunked_flag` | change | with_brainkm | 1 | N | — | 0 | dry_run | dry-run |
| `c_longmemeval_chunked_flag` | change | without | 1 | N | — | 0 | dry_run | dry-run |
| `c_cli_longmemeval_chunked` | change | with_brainkm | 1 | N | — | 0 | dry_run | dry-run |
| `c_cli_longmemeval_chunked` | change | without | 1 | N | — | 0 | dry_run | dry-run |
| `c_comparison_doc` | change | with_brainkm | 1 | N | — | 0 | dry_run | dry-run |
| `c_comparison_doc` | change | without | 1 | N | — | 0 | dry_run | dry-run |

## Caveats

- Nondeterministic LLM runs; publish with **repeats ≥ 3**.
- Costs real Cursor API tokens (`CURSOR_API_KEY` required for live runs).
- Knowledge tasks graded by regex; change tasks by shell checkers.
- Ollama judge is optional tiebreak only — never sole grader.
- Dry-run plans costs without calling the API.

- Dry-run only — no Cursor API calls.
- Set CURSOR_API_KEY and omit --dry-run for live A/B.
