# End-task A/B scorecard (agent with brainkm vs without)

- **fixture:** endtask_v1
- **model:** llama-3.3-70b-versatile
- **dry_run:** False
- **runs recorded:** 10

## Headline

| Arm | Success | Mean prompt tokens |
|-----|---------|---------------------|
| **with brainkm** | 5/5 (100%) | 523 (3.9× prompt tokens vs without — pack injection) |
| without | 0/5 (0%) | 136 |

> Agent with brainkm solved **5/5** vs **0/5** without (3.9× prompt tokens vs without — pack injection).

## By class

### knowledge

- `with_brainkm`: 5/5
- `without`: 0/5

## Per-run table

| Task | Class | Arm | Rep | Pass | Tokens | Wall ms | Status | Detail |
|------|-------|-----|-----|------|--------|---------|--------|--------|
| `k_budget_cap` | knowledge | with_brainkm | 1 | Y | 665 | 16507 | finished | all_patterns |
| `k_budget_cap` | knowledge | without | 1 | N | 148 | 43521 | finished | missing=['1500'] |
| `k_remember_role` | knowledge | with_brainkm | 1 | Y | 590 | 938 | finished | all_patterns |
| `k_remember_role` | knowledge | without | 1 | N | 135 | 814 | finished | missing=['(?i)pin'] |
| `k_fusion_mode` | knowledge | with_brainkm | 1 | Y | 560 | 841 | finished | all_patterns |
| `k_fusion_mode` | knowledge | without | 1 | N | 138 | 848 | finished | missing=['fts_primary', '(?i)(rrf\|0\\.37\|collapse\|noise)'] |
| `k_precompact` | knowledge | with_brainkm | 1 | Y | 296 | 776 | finished | all_patterns |
| `k_precompact` | knowledge | without | 1 | N | 128 | 907 | finished | missing=['(?i)(precompact\|handover)', '(?i)(brain\\.db\|neuron\|surviv)'] |
| `k_layers` | knowledge | with_brainkm | 1 | Y | 502 | 655 | finished | all_patterns |
| `k_layers` | knowledge | without | 1 | N | 129 | 806 | finished | missing=['(?i)service', '(?i)(adapter\|SQLite)'] |

## Caveats

- Nondeterministic LLM runs; publish with **repeats ≥ 3**.
- Costs real Cursor API tokens (`CURSOR_API_KEY` required for live runs).
- Knowledge tasks graded by regex; change tasks by shell checkers.
- Ollama judge is optional tiebreak only — never sole grader.
- Dry-run plans costs without calling the API.

- backend=groq (knowledge pack A/B; not full Cursor agent)
- repeats=1
- Change tasks skipped on groq backend.
