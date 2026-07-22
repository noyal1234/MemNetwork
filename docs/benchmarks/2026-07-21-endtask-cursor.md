# End-task A/B scorecard (agent with brainkm vs without)

- **fixture:** endtask_v1
- **model:** composer-2.5
- **dry_run:** False
- **runs recorded:** 120

## Headline

| Arm | Success | Mean prompt tokens |
|-----|---------|---------------------|
| **with brainkm** | 60/60 (100%) | 76940 (5% fewer prompt tokens vs without) |
| without | 60/60 (100%) | 80762 |

> Agent with brainkm solved **60/60** vs **60/60** without (5% fewer prompt tokens vs without).

## By class

### change

- `with_brainkm`: 24/24
- `without`: 24/24

### knowledge

- `with_brainkm`: 36/36
- `without`: 36/36

## Per-run table

| Task | Class | Arm | Rep | Pass | Tokens | Wall ms | Status | Detail |
|------|-------|-----|-----|------|--------|---------|--------|--------|
| `k_budget_cap` | knowledge | with_brainkm | 1 | Y | 62501 | 26994 | finished | all_patterns |
| `k_budget_cap` | knowledge | with_brainkm | 2 | Y | 63457 | 17767 | finished | all_patterns |
| `k_budget_cap` | knowledge | with_brainkm | 3 | Y | 104902 | 19285 | finished | all_patterns |
| `k_budget_cap` | knowledge | without | 1 | Y | 92401 | 19739 | finished | all_patterns |
| `k_budget_cap` | knowledge | without | 2 | Y | 118534 | 22120 | finished | all_patterns |
| `k_budget_cap` | knowledge | without | 3 | Y | 83787 | 23257 | finished | all_patterns |
| `k_remember_role` | knowledge | with_brainkm | 1 | Y | 62651 | 18216 | finished | all_patterns |
| `k_remember_role` | knowledge | with_brainkm | 2 | Y | 67541 | 18232 | finished | all_patterns |
| `k_remember_role` | knowledge | with_brainkm | 3 | Y | 84186 | 19756 | finished | all_patterns |
| `k_remember_role` | knowledge | without | 1 | Y | 82611 | 16643 | finished | all_patterns |
| `k_remember_role` | knowledge | without | 2 | Y | 56031 | 16547 | finished | all_patterns |
| `k_remember_role` | knowledge | without | 3 | Y | 56349 | 14498 | finished | all_patterns |
| `k_fusion_mode` | knowledge | with_brainkm | 1 | Y | 88402 | 20181 | finished | all_patterns |
| `k_fusion_mode` | knowledge | with_brainkm | 2 | Y | 114243 | 23453 | finished | all_patterns |
| `k_fusion_mode` | knowledge | with_brainkm | 3 | Y | 88143 | 21581 | finished | all_patterns |
| `k_fusion_mode` | knowledge | without | 1 | Y | 133124 | 25903 | finished | all_patterns |
| `k_fusion_mode` | knowledge | without | 2 | Y | 108017 | 21262 | finished | all_patterns |
| `k_fusion_mode` | knowledge | without | 3 | Y | 104076 | 25778 | finished | all_patterns |
| `k_precompact` | knowledge | with_brainkm | 1 | Y | 147105 | 26252 | finished | all_patterns |
| `k_precompact` | knowledge | with_brainkm | 2 | Y | 151210 | 33492 | finished | all_patterns |
| `k_precompact` | knowledge | with_brainkm | 3 | Y | 186130 | 26935 | finished | all_patterns |
| `k_precompact` | knowledge | without | 1 | Y | 104230 | 24409 | finished | all_patterns |
| `k_precompact` | knowledge | without | 2 | Y | 143936 | 24401 | finished | all_patterns |
| `k_precompact` | knowledge | without | 3 | Y | 81405 | 21204 | finished | all_patterns |
| `k_layers` | knowledge | with_brainkm | 1 | Y | 64851 | 20243 | finished | all_patterns |
| `k_layers` | knowledge | with_brainkm | 2 | Y | 123175 | 22643 | finished | all_patterns |
| `k_layers` | knowledge | with_brainkm | 3 | Y | 156499 | 25769 | finished | all_patterns |
| `k_layers` | knowledge | without | 1 | Y | 103190 | 28055 | finished | all_patterns |
| `k_layers` | knowledge | without | 2 | Y | 105791 | 19259 | finished | all_patterns |
| `k_layers` | knowledge | without | 3 | Y | 115708 | 21583 | finished | all_patterns |
| `k_recall_budget` | knowledge | with_brainkm | 1 | Y | 30524 | 16955 | finished | all_patterns |
| `k_recall_budget` | knowledge | with_brainkm | 2 | Y | 60995 | 17016 | finished | all_patterns |
| `k_recall_budget` | knowledge | with_brainkm | 3 | Y | 108418 | 20902 | finished | all_patterns |
| `k_recall_budget` | knowledge | without | 1 | Y | 47457 | 14707 | finished | all_patterns |
| `k_recall_budget` | knowledge | without | 2 | Y | 47503 | 15873 | finished | all_patterns |
| `k_recall_budget` | knowledge | without | 3 | Y | 46789 | 16115 | finished | all_patterns |
| `k_dual_grain` | knowledge | with_brainkm | 1 | Y | 102660 | 31665 | finished | all_patterns |
| `k_dual_grain` | knowledge | with_brainkm | 2 | Y | 87876 | 23849 | finished | all_patterns |
| `k_dual_grain` | knowledge | with_brainkm | 3 | Y | 81713 | 28085 | finished | all_patterns |
| `k_dual_grain` | knowledge | without | 1 | Y | 77518 | 21909 | finished | all_patterns |
| `k_dual_grain` | knowledge | without | 2 | Y | 87426 | 20136 | finished | all_patterns |
| `k_dual_grain` | knowledge | without | 3 | Y | 82971 | 20847 | finished | all_patterns |
| `k_no_secrets` | knowledge | with_brainkm | 1 | Y | 81046 | 19361 | finished | all_patterns |
| `k_no_secrets` | knowledge | with_brainkm | 2 | Y | 67431 | 14631 | finished | all_patterns |
| `k_no_secrets` | knowledge | with_brainkm | 3 | Y | 61795 | 17794 | finished | all_patterns |
| `k_no_secrets` | knowledge | without | 1 | Y | 102017 | 20571 | finished | all_patterns |
| `k_no_secrets` | knowledge | without | 2 | Y | 54476 | 14241 | finished | all_patterns |
| `k_no_secrets` | knowledge | without | 3 | Y | 79428 | 17842 | finished | all_patterns |
| `k_clients` | knowledge | with_brainkm | 1 | Y | 89592 | 24270 | finished | all_patterns |
| `k_clients` | knowledge | with_brainkm | 2 | Y | 64197 | 18662 | finished | all_patterns |
| `k_clients` | knowledge | with_brainkm | 3 | Y | 64372 | 15684 | finished | all_patterns |
| `k_clients` | knowledge | without | 1 | Y | 54784 | 13898 | finished | all_patterns |
| `k_clients` | knowledge | without | 2 | Y | 55663 | 13465 | finished | all_patterns |
| `k_clients` | knowledge | without | 3 | Y | 54951 | 14250 | finished | all_patterns |
| `k_traverse` | knowledge | with_brainkm | 1 | Y | 25929 | 11035 | finished | all_patterns |
| `k_traverse` | knowledge | with_brainkm | 2 | Y | 25921 | 13196 | finished | all_patterns |
| `k_traverse` | knowledge | with_brainkm | 3 | Y | 25716 | 11363 | finished | all_patterns |
| `k_traverse` | knowledge | without | 1 | Y | 50293 | 14741 | finished | all_patterns |
| `k_traverse` | knowledge | without | 2 | Y | 94809 | 17819 | finished | all_patterns |
| `k_traverse` | knowledge | without | 3 | Y | 72166 | 20389 | finished | all_patterns |
| `k_config_env` | knowledge | with_brainkm | 1 | Y | 132558 | 26151 | finished | all_patterns |
| `k_config_env` | knowledge | with_brainkm | 2 | Y | 144249 | 25187 | finished | all_patterns |
| `k_config_env` | knowledge | with_brainkm | 3 | Y | 113145 | 39571 | finished | all_patterns |
| `k_config_env` | knowledge | without | 1 | Y | 156417 | 44781 | finished | all_patterns |
| `k_config_env` | knowledge | without | 2 | Y | 246094 | 29874 | finished | all_patterns |
| `k_config_env` | knowledge | without | 3 | Y | 136488 | 24620 | finished | all_patterns |
| `k_python_version` | knowledge | with_brainkm | 1 | Y | 101956 | 21037 | finished | all_patterns |
| `k_python_version` | knowledge | with_brainkm | 2 | Y | 85236 | 22638 | finished | all_patterns |
| `k_python_version` | knowledge | with_brainkm | 3 | Y | 86272 | 19432 | finished | all_patterns |
| `k_python_version` | knowledge | without | 1 | Y | 122259 | 25946 | finished | all_patterns |
| `k_python_version` | knowledge | without | 2 | Y | 66437 | 18846 | finished | all_patterns |
| `k_python_version` | knowledge | without | 3 | Y | 113272 | 23158 | finished | all_patterns |
| `c_ir_metrics_export` | change | with_brainkm | 1 | Y | 58985 | 23328 | finished | 41:def recall_at_budget( \| 56:def pack_noise_rate( |
| `c_ir_metrics_export` | change | with_brainkm | 2 | Y | 118736 | 53680 | finished | 41:def recall_at_budget( \| 56:def pack_noise_rate( |
| `c_ir_metrics_export` | change | with_brainkm | 3 | Y | 135504 | 46964 | finished | 41:def recall_at_budget( \| 56:def pack_noise_rate( |
| `c_ir_metrics_export` | change | without | 1 | Y | 225977 | 38154 | finished | 41:def recall_at_budget( \| 56:def pack_noise_rate( |
| `c_ir_metrics_export` | change | without | 2 | Y | 168578 | 37756 | finished | 41:def recall_at_budget( \| 56:def pack_noise_rate( |
| `c_ir_metrics_export` | change | without | 3 | Y | 130219 | 34073 | finished | 41:def recall_at_budget( \| 56:def pack_noise_rate( |
| `c_bench_runner_staleness` | change | with_brainkm | 1 | Y | 44413 | 15565 | finished | 119:    "staleness": lambda _db: __import__( \| 120:        "brainkm.services.staleness_bench", fromlist=["run_staleness |
| `c_bench_runner_staleness` | change | with_brainkm | 2 | Y | 27619 | 15251 | finished | 119:    "staleness": lambda _db: __import__( \| 120:        "brainkm.services.staleness_bench", fromlist=["run_staleness |
| `c_bench_runner_staleness` | change | with_brainkm | 3 | Y | 27401 | 15668 | finished | 119:    "staleness": lambda _db: __import__( \| 120:        "brainkm.services.staleness_bench", fromlist=["run_staleness |
| `c_bench_runner_staleness` | change | without | 1 | Y | 26327 | 12686 | finished | 119:    "staleness": lambda _db: __import__( \| 120:        "brainkm.services.staleness_bench", fromlist=["run_staleness |
| `c_bench_runner_staleness` | change | without | 2 | Y | 26322 | 14573 | finished | 119:    "staleness": lambda _db: __import__( \| 120:        "brainkm.services.staleness_bench", fromlist=["run_staleness |
| `c_bench_runner_staleness` | change | without | 3 | Y | 26320 | 26710 | finished | 119:    "staleness": lambda _db: __import__( \| 120:        "brainkm.services.staleness_bench", fromlist=["run_staleness |
| `c_fusion_mode_field` | change | with_brainkm | 1 | Y | 29480 | 14466 | finished | 173:    fusion_mode: Literal["rrf", "fts_primary"] = Field( \| 173:    fusion_mode: Literal["rrf", "fts_primary"] = Fiel |
| `c_fusion_mode_field` | change | with_brainkm | 2 | Y | 48253 | 18458 | finished | 173:    fusion_mode: Literal["rrf", "fts_primary"] = Field( \| 173:    fusion_mode: Literal["rrf", "fts_primary"] = Fiel |
| `c_fusion_mode_field` | change | with_brainkm | 3 | Y | 29696 | 14564 | finished | 173:    fusion_mode: Literal["rrf", "fts_primary"] = Field( \| 173:    fusion_mode: Literal["rrf", "fts_primary"] = Fiel |
| `c_fusion_mode_field` | change | without | 1 | Y | 46078 | 12601 | finished | 173:    fusion_mode: Literal["rrf", "fts_primary"] = Field( \| 173:    fusion_mode: Literal["rrf", "fts_primary"] = Fiel |
| `c_fusion_mode_field` | change | without | 2 | Y | 28393 | 11804 | finished | 173:    fusion_mode: Literal["rrf", "fts_primary"] = Field( \| 173:    fusion_mode: Literal["rrf", "fts_primary"] = Fiel |
| `c_fusion_mode_field` | change | without | 3 | Y | 28392 | 13886 | finished | 173:    fusion_mode: Literal["rrf", "fts_primary"] = Field( \| 173:    fusion_mode: Literal["rrf", "fts_primary"] = Fiel |
| `c_budget_default` | change | with_brainkm | 1 | Y | 47426 | 15302 | finished | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000) |
| `c_budget_default` | change | with_brainkm | 2 | Y | 49396 | 14339 | finished | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000) |
| `c_budget_default` | change | with_brainkm | 3 | Y | 29386 | 14158 | finished | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000) |
| `c_budget_default` | change | without | 1 | Y | 25562 | 11461 | finished | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000) |
| `c_budget_default` | change | without | 2 | Y | 42713 | 13887 | finished | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000) |
| `c_budget_default` | change | without | 3 | Y | 28086 | 10723 | finished | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000) |
| `c_endtask_fixture_present` | change | with_brainkm | 1 | Y | 58961 | 15632 | finished | 2:  "id": "endtask_v1", |
| `c_endtask_fixture_present` | change | with_brainkm | 2 | Y | 46213 | 15286 | finished | 2:  "id": "endtask_v1", |
| `c_endtask_fixture_present` | change | with_brainkm | 3 | Y | 51645 | 17634 | finished | 2:  "id": "endtask_v1", |
| `c_endtask_fixture_present` | change | without | 1 | Y | 44349 | 15798 | finished | 2:  "id": "endtask_v1", |
| `c_endtask_fixture_present` | change | without | 2 | Y | 45190 | 13495 | finished | 2:  "id": "endtask_v1", |
| `c_endtask_fixture_present` | change | without | 3 | Y | 44352 | 17133 | finished | 2:  "id": "endtask_v1", |
| `c_longmemeval_chunked_flag` | change | with_brainkm | 1 | Y | 54461 | 18886 | finished | 9:Legacy ``--chunked`` indexes everything as overlapping chunks (historical comparison). \| 207:    chunked: bool, \| 21 |
| `c_longmemeval_chunked_flag` | change | with_brainkm | 2 | Y | 41023 | 14582 | finished | 9:Legacy ``--chunked`` indexes everything as overlapping chunks (historical comparison). \| 207:    chunked: bool, \| 21 |
| `c_longmemeval_chunked_flag` | change | with_brainkm | 3 | Y | 41073 | 25022 | finished | 9:Legacy ``--chunked`` indexes everything as overlapping chunks (historical comparison). \| 207:    chunked: bool, \| 21 |
| `c_longmemeval_chunked_flag` | change | without | 1 | Y | 39054 | 12495 | finished | 9:Legacy ``--chunked`` indexes everything as overlapping chunks (historical comparison). \| 207:    chunked: bool, \| 21 |
| `c_longmemeval_chunked_flag` | change | without | 2 | Y | 39033 | 17488 | finished | 9:Legacy ``--chunked`` indexes everything as overlapping chunks (historical comparison). \| 207:    chunked: bool, \| 21 |
| `c_longmemeval_chunked_flag` | change | without | 3 | Y | 36935 | 17625 | finished | 9:Legacy ``--chunked`` indexes everything as overlapping chunks (historical comparison). \| 207:    chunked: bool, \| 21 |
| `c_cli_longmemeval_chunked` | change | with_brainkm | 1 | Y | 95462 | 27944 | finished | 679:    chunked: bool = typer.Option( \| 681:        "--chunked", \| 705:            chunked=chunked, |
| `c_cli_longmemeval_chunked` | change | with_brainkm | 2 | Y | 197149 | 26720 | finished | 679:    chunked: bool = typer.Option( \| 681:        "--chunked", \| 705:            chunked=chunked, |
| `c_cli_longmemeval_chunked` | change | with_brainkm | 3 | Y | 96105 | 27692 | finished | 679:    chunked: bool = typer.Option( \| 681:        "--chunked", \| 705:            chunked=chunked, |
| `c_cli_longmemeval_chunked` | change | without | 1 | Y | 141514 | 22961 | finished | 679:    chunked: bool = typer.Option( \| 681:        "--chunked", \| 705:            chunked=chunked, |
| `c_cli_longmemeval_chunked` | change | without | 2 | Y | 68200 | 16043 | finished | 679:    chunked: bool = typer.Option( \| 681:        "--chunked", \| 705:            chunked=chunked, |
| `c_cli_longmemeval_chunked` | change | without | 3 | Y | 166149 | 30236 | finished | 679:    chunked: bool = typer.Option( \| 681:        "--chunked", \| 705:            chunked=chunked, |
| `c_comparison_doc` | change | with_brainkm | 1 | Y | 28433 | 11850 | finished | 5:## Headline (brainkm product metric): recall@budget \| 8:contract is **recall@budget**: is any gold id present in `tru |
| `c_comparison_doc` | change | with_brainkm | 2 | Y | 26493 | 12827 | finished | 5:## Headline (brainkm product metric): recall@budget \| 8:contract is **recall@budget**: is any gold id present in `tru |
| `c_comparison_doc` | change | with_brainkm | 3 | Y | 26481 | 11985 | finished | 5:## Headline (brainkm product metric): recall@budget \| 8:contract is **recall@budget**: is any gold id present in `tru |
| `c_comparison_doc` | change | without | 1 | Y | 27130 | 9985 | finished | 5:## Headline (brainkm product metric): recall@budget \| 8:contract is **recall@budget**: is any gold id present in `tru |
| `c_comparison_doc` | change | without | 2 | Y | 25297 | 10705 | finished | 5:## Headline (brainkm product metric): recall@budget \| 8:contract is **recall@budget**: is any gold id present in `tru |
| `c_comparison_doc` | change | without | 3 | Y | 27128 | 10626 | finished | 5:## Headline (brainkm product metric): recall@budget \| 8:contract is **recall@budget**: is any gold id present in `tru |

## Caveats

- Nondeterministic LLM runs; publish with **repeats ≥ 3**.
- Costs real Cursor API tokens (`CURSOR_API_KEY` required for live runs).
- Knowledge tasks graded by regex; change tasks by shell checkers.
- Ollama judge is optional tiebreak only — never sole grader.
- Dry-run plans costs without calling the API.

- backend=cursor
- repeats=3
- Nondeterministic — re-run with --repeats 3 before publishing claims.
