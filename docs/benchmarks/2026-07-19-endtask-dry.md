# End-task A/B scorecard (agent with brainkm vs without)

- **fixture:** endtask_v1
- **model:** composer-2.5
- **dry_run:** True
- **runs recorded:** 10

## Headline

| Arm | Success | Mean context tokens |
|-----|---------|---------------------|
| **with brainkm** | dry-run planned n=5 | — |
| without | dry-run planned n=5 | — |

## By class

### knowledge

- `with_brainkm`: dry-run n=5
- `without`: dry-run n=5

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

## Caveats

- Nondeterministic LLM runs; publish with **repeats ≥ 3**.
- Costs real Cursor API tokens (`CURSOR_API_KEY` required for live runs).
- Knowledge tasks graded by regex; change tasks by shell checkers.
- Ollama judge is optional tiebreak only — never sole grader.
- Dry-run plans costs without calling the API.

- Dry-run only — no Cursor API calls.
- Set CURSOR_API_KEY and omit --dry-run for live A/B.
