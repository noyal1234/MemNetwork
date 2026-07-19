# Common Memory Axes (CMA) scorecard

- **brainkm version:** 0.5.0
- **commit:** abc20bf
- **machine:** macOS-26.5.2-x86_64-i386-64bit
- **semantic embeddings:** off (FTS+graph default)
- **command:** `brainkm bench run cma`
- **suite:** `78/78` (100%)

## Headline

```
CMA 78/78 fixture=cma_v3 corpus_queries=60
  recall@budget=0.833 (floor>=0.80, n=42) pack_noise=0.885 (n=42)
  micro=1.000 (floor>=0.70) hard=1.000 (floor>=0.55, n=32)  # regression gate
  pack=323 (max<=1500, n=42) recall_p95=13.2ms (target<=800) pack_p95=18.0ms (target<=1200)
  baselines: brain=1.000 bm25=0.878 lift=+0.122 n=41 (gate_lift>=-0.05 met=True) | brain=1.000 title=0.829 lift=+0.171 n=41 (gate_lift>=-0.05 met=True)
  hard_slice_lift: brain=1.000 bm25=0.545 lift=+0.455 n=11 (floor>=0.15)
  abilities: abstention=9/9 extraction=26/26 knowledge_update=5/5 multi_hop=10/10 multi_session=4/4 procedure=4/4 theme_leak=2/2
```

## Cases

| Status | Case | Detail |
|--------|------|--------|
| PASS | `extraction/cma_q_ext_jwt` | top=['cma_v3_syn_auth', 'cma_v3_br_auth', 'cma_ms_s2_auth'] expected=['cma_mem_auth_3', 'cma_v3_syn_auth', 'cma_ms_s2_auth', 'cma_v3_br_auth'] abstained=False bm25=1 title=1 pack=334/775 r@budget=1 noise=0.67 |
| PASS | `extraction/cma_q_ext_budget` | top=['cma_budget_new', 'cma_v3_syn_budget', 'cma_ms_s2_budget'] expected=['cma_mem_budget_0', 'cma_budget_new', 'cma_ms_s2_budget'] abstained=False bm25=1 title=1 pack=416/1450 r@budget=1 noise=0.75 |
| PASS | `extraction/cma_q_ext_graphify` | top=['cma_mem_graph_1', 'cma_mem_graph_2', 'cma_mem_graph_0'] expected=['cma_mem_graph_1'] abstained=False bm25=1 title=1 pack=226/1450 r@budget=1 noise=0.83 |
| PASS | `extraction/cma_q_ext_precompact` | top=['cma_v3_syn_compact', 'cma_mem_hooks_1', 'cma_v3_br_compact'] expected=['cma_mem_hooks_1', 'cma_mem_handover_0', 'cma_proc_compact'] abstained=False bm25=1 title=1 pack=375/1450 r@budget=1 noise=0.80 |
| PASS | `extraction/cma_q_ext_redact` | top=['cma_v3_syn_redact', 'cma_v3_br_redact', 'cma_mem_redaction_2'] expected=['cma_mem_redaction_0'] abstained=False bm25=1 title=1 pack=319/1450 r@budget=0 noise=1.00 |
| PASS | `extraction/cma_q_ext_writequeue` | top=['cma_v3_syn_writer', 'cma_v3_br_writer', 'cma_mem_queue_2'] expected=['cma_mem_queue_0'] abstained=False bm25=1 title=1 pack=318/1450 r@budget=1 noise=0.89 |
| PASS | `extraction/cma_q_ext_frozen` | top=['cma_mem_handover_1', 'cma_mem_handover_2', 'cma_mem_handover_3'] expected=['cma_mem_handover_1'] abstained=False bm25=1 title=1 pack=272/1450 r@budget=1 noise=0.86 |
| PASS | `extraction/cma_q_ext_http` | top=['cma_v3_syn_serve', 'cma_v3_br_serve', 'cma_mem_mcp_1'] expected=['cma_mem_mcp_1'] abstained=False bm25=1 title=1 pack=275/1450 r@budget=1 noise=0.88 |
| PASS | `extraction/cma_q_ext_bm25` | top=['cma_mem_fts_1', 'cma_mem_fts_2', 'cma_mem_fts_3'] expected=['cma_mem_fts_0'] abstained=False bm25=1 title=1 pack=273/1450 r@budget=0 noise=1.00 |
| PASS | `extraction/cma_q_ext_minilm` | top=['cma_mem_semantic_1', 'cma_mem_semantic_2', 'cma_mem_semantic_0'] expected=['cma_mem_semantic_0'] abstained=False bm25=1 title=1 pack=233/1450 r@budget=0 noise=1.00 |
| PASS | `extraction/cma_q_ext_tui` | top=['cma_mem_install_1', 'cma_mem_install_2', 'cma_mem_install_0'] expected=['cma_mem_install_0'] abstained=False bm25=1 title=1 pack=280/1450 r@budget=0 noise=1.00 |
| PASS | `extraction/cma_q_ext_ollama` | top=['cma_distill_new', 'cma_mem_distill_1', 'cma_mem_distill_2'] expected=['cma_mem_distill_1'] abstained=False bm25=1 title=1 pack=358/1450 r@budget=1 noise=0.89 |
| PASS | `knowledge_update/cma_q_upd_ttl` | top=['cma_ttl_new', 'cma_v3_ttl_new', 'cma_budget_new'] expected=['cma_ttl_new'] abstained=False bm25=1 title=1 pack=370/1450 r@budget=1 noise=0.92 |
| PASS | `knowledge_update/cma_q_upd_budget` | top=['cma_budget_new', 'cma_ttl_new', 'cma_mem_budget_1'] expected=['cma_budget_new'] abstained=False bm25=1 title=1 pack=435/1450 r@budget=1 noise=0.92 |
| PASS | `abstention/cma_q_abs_0` | abstained=True hits=0 |
| PASS | `abstention/cma_q_abs_1` | abstained=True hits=0 |
| PASS | `abstention/cma_q_abs_2` | abstained=True hits=0 |
| PASS | `abstention/cma_q_abs_3` | abstained=True hits=0 |
| PASS | `abstention/cma_q_abs_4` | abstained=True hits=0 |
| PASS | `abstention/cma_q_abs_5` | abstained=True hits=0 |
| PASS | `multi_hop/cma_q_hop_dispatch` | neighbors=10 resolved=cma_fn_dispatch_tool ms=5.2 |
| PASS | `multi_hop/cma_q_hop_pack` | neighbors=11 resolved=cma_fn_compile_context_pack ms=5.7 |
| PASS | `multi_hop/cma_q_hop_path` | neighbors=3 resolved=cma_file_recall_py ms=1.6 |
| PASS | `multi_hop/cma_q_hop_recall_q` | top=['cma_fn_compile_context_pack', 'cma_v3_br_diversify', 'cma_fn_diversify_hits'] expected=['cma_fn_compile_context_pack'] abstained=False pack=372/1450 r@budget=0 noise=1.00 |
| PASS | `procedure/cma_q_proc_auth` | top=['cma_proc_auth', 'cma_mem_auth_1', 'cma_ms_s2_auth'] expected=['cma_proc_auth'] abstained=False bm25=1 title=1 pack=277/1075 r@budget=1 noise=0.88 |
| PASS | `procedure/cma_q_proc_graph` | top=['cma_v3_syn_graph', 'cma_v3_br_graph', 'cma_mem_graph_1'] expected=['cma_proc_graph'] abstained=False bm25=1 title=1 pack=329/1450 r@budget=1 noise=0.90 |
| PASS | `procedure/cma_q_proc_compact` | top=['cma_v3_syn_compact', 'cma_v3_br_compact', 'cma_proc_compact'] expected=['cma_proc_compact'] abstained=False bm25=1 title=1 pack=231/1450 r@budget=1 noise=0.86 |
| PASS | `procedure/cma_q_proc_serve` | top=['cma_v3_syn_serve', 'cma_v3_br_serve', 'cma_proc_serve'] expected=['cma_proc_serve'] abstained=False bm25=1 title=1 pack=416/1450 r@budget=1 noise=0.91 |
| PASS | `extraction/cma_q_ext_para_jwt` | top=['cma_v3_syn_auth', 'cma_v3_br_auth', 'cma_v3_syn_budget'] expected=['cma_ms_s2_auth', 'cma_mem_auth_3'] abstained=False bm25=1 title=1 pack=394/1450 r@budget=1 noise=0.92 |
| PASS | `extraction/cma_q_ext_para_budget` | top=['cma_v3_syn_budget', 'cma_budget_new', 'cma_v3_br_budget'] expected=['cma_ms_s2_budget', 'cma_budget_new', 'cma_mem_budget_0', 'cma_ms_s1_budget'] abstained=False bm25=1 title=1 pack=395/1450 r@budget=1 noise=0.75 |
| PASS | `extraction/cma_q_ext_para_graph` | top=['cma_v3_syn_graph', 'cma_v3_br_graph', 'cma_v3_syn_compact'] expected=['cma_ms_s2_graph', 'cma_proc_graph'] abstained=False bm25=1 title=1 pack=313/850 r@budget=1 noise=0.80 |
| PASS | `extraction/cma_q_ext_para_remember` | top=['cma_v3_syn_hooks', 'cma_v3_br_hooks', 'cma_v3_syn_budget'] expected=['cma_ms_s4_hooks', 'cma_mem_hooks_3'] abstained=False bm25=1 title=1 pack=430/850 r@budget=1 noise=0.85 |
| PASS | `extraction/cma_q_ext_para_redact` | top=['cma_v3_syn_redact', 'cma_v3_br_redact', 'cma_ttl_new'] expected=['cma_mem_redaction_0', 'cma_mem_redaction_1'] abstained=False bm25=1 title=1 pack=382/1450 r@budget=1 noise=0.91 |
| PASS | `extraction/cma_q_ext_para_wal` | top=['cma_v3_syn_writer', 'cma_v3_br_writer', 'cma_v3_ttl_new'] expected=['cma_mem_queue_0', 'cma_mem_queue_1'] abstained=False bm25=1 title=1 pack=351/850 r@budget=1 noise=0.91 |
| PASS | `multi_session/cma_q_ms_auth` | prefer_hit top=['cma_v3_syn_auth', 'cma_v3_br_auth', 'cma_ms_s2_auth'] expected=['cma_ms_s2_auth', 'cma_ms_s1_auth'] abstained=False bm25=1 title=1 pack=307/1450 r@budget=1 noise=0.89 |
| PASS | `multi_session/cma_q_ms_graph` | prefer_miss top=['cma_ms_s1_graph'] expected=['cma_ms_s2_graph', 'cma_ms_s1_graph'] abstained=False bm25=1 title=1 pack=210/850 r@budget=1 noise=0.83 |
| PASS | `multi_session/cma_q_ms_budget` | prefer_miss top=['cma_v3_syn_budget', 'cma_v3_ttl_new', 'cma_ttl_new'] expected=['cma_ms_s2_budget', 'cma_ms_s1_budget', 'cma_v3_syn_budget', 'cma_budget_new'] abstained=False bm25=1 title=1 pack=396/1450 r@budget=1 noise=0.77 |
| PASS | `multi_session/cma_q_ms_hooks` | prefer_miss top=['cma_v3_syn_hooks', 'cma_v3_br_hooks', 'cma_ms_s3_hooks'] expected=['cma_ms_s4_hooks', 'cma_ms_s3_hooks'] abstained=False bm25=1 title=1 pack=292/1450 r@budget=1 noise=0.78 |
| PASS | `knowledge_update/cma_q_upd_distill` | top=['cma_distill_new', 'cma_v3_syn_hooks', 'cma_budget_new'] expected=['cma_distill_new'] abstained=False bm25=1 title=1 pack=408/1450 r@budget=1 noise=0.92 |
| PASS | `knowledge_update/cma_q_upd_observe` | top=['cma_obs_new', 'cma_v3_syn_hooks', 'cma_v3_br_hooks'] expected=['cma_obs_new'] abstained=False bm25=1 title=1 pack=359/1450 r@budget=1 noise=0.91 |
| PASS | `theme_leak/cma_q_theme_neo4j` | leaked=0 abstained=True hits=0 |
| PASS | `theme_leak/cma_q_abs_leak_pinecone_key` | leaked=0 abstained=True hits=0 |
| PASS | `abstention/cma_q_abs_leak_nba` | abstained=True hits=0 |
| PASS | `abstention/cma_q_abs_leak_weather` | abstained=True hits=0 |
| PASS | `multi_hop/cma_q_hop_diversify` | neighbors=11 resolved=cma_fn_compile_context_pack ms=5.3 |
| PASS | `multi_hop/cma_q_hop_promote` | neighbors=5 resolved=cma_fn_auto_observe ms=2.7 |
| PASS | `abstention/cma_q_abs_cassandra` | abstained=True hits=0 |
| PASS | `multi_hop/cma_v3_q_hop_who_calls_pack` | neighbors=11 resolved=cma_fn_compile_context_pack ms=5.1 |
| PASS | `multi_hop/cma_v3_q_hop_who_calls_observe` | neighbors=5 resolved=cma_fn_auto_observe ms=2.7 |
| PASS | `extraction/cma_v3_q_budget` | top=['cma_v3_syn_budget', 'cma_v3_br_budget', 'cma_v3_noise_limit_rate'] expected=['cma_v3_syn_budget'] abstained=False bm25=0 title=0 hard_slice=1 pack=301/1450 r@budget=1 noise=0.90 |
| PASS | `extraction/cma_v3_q_auth` | top=['cma_v3_syn_auth', 'cma_v3_br_auth', 'cma_ms_s2_auth'] expected=['cma_v3_syn_auth'] abstained=False bm25=0 title=0 hard_slice=1 pack=265/1450 r@budget=1 noise=0.88 |
| PASS | `extraction/cma_v3_q_graph` | top=['cma_v3_syn_graph', 'cma_v3_br_graph', 'cma_v3_syn_compact'] expected=['cma_v3_syn_graph'] abstained=False bm25=1 title=1 hard_slice=1 pack=315/850 r@budget=1 noise=0.90 |
| PASS | `extraction/cma_v3_q_hooks` | top=['cma_v3_syn_hooks', 'cma_v3_br_hooks', 'cma_ms_s3_hooks'] expected=['cma_v3_syn_hooks'] abstained=False bm25=1 title=1 hard_slice=1 pack=287/1450 r@budget=1 noise=0.89 |
| PASS | `extraction/cma_v3_q_redact` | top=['cma_v3_br_redact', 'cma_v3_syn_redact'] expected=['cma_v3_syn_redact'] abstained=False bm25=0 title=0 hard_slice=1 pack=230/1450 r@budget=1 noise=0.86 |
| PASS | `extraction/cma_v3_q_writer` | top=['cma_v3_br_writer', 'cma_v3_syn_writer', 'cma_v3_ttl_new'] expected=['cma_v3_syn_writer'] abstained=False bm25=1 title=0 hard_slice=1 pack=373/850 r@budget=1 noise=0.91 |
| PASS | `extraction/cma_v3_q_compact` | top=['cma_v3_syn_compact', 'cma_v3_br_compact', 'cma_v3_br_diversify'] expected=['cma_v3_syn_compact'] abstained=False bm25=1 title=1 hard_slice=1 pack=260/850 r@budget=1 noise=0.88 |
| PASS | `extraction/cma_v3_q_serve` | top=['cma_v3_syn_serve', 'cma_v3_br_serve', 'cma_v3_ttl_new'] expected=['cma_v3_syn_serve'] abstained=False bm25=1 title=0 hard_slice=1 pack=441/1450 r@budget=1 noise=0.92 |
| PASS | `multi_hop/cma_v3_q_diversify` | top=['cma_v3_br_diversify', 'cma_fn_diversify_hits', 'cma_fn_compile_context_pack'] expected=['cma_fn_diversify_hits'] abstained=False bm25=0 title=0 hard_slice=1 pack=260/850 r@budget=0 noise=1.00 |
| PASS | `multi_hop/cma_v3_q_promote` | top=['cma_v3_br_promote', 'cma_fn_promote_observation', 'cma_fn_auto_observe'] expected=['cma_fn_promote_observation'] abstained=False bm25=0 title=0 hard_slice=1 pack=210/1450 r@budget=0 noise=1.00 |
| PASS | `knowledge_update/cma_v3_q_ttl` | top=['cma_v3_ttl_new', 'cma_v3_br_ttl', 'cma_ttl_new'] expected=['cma_v3_ttl_new'] abstained=False bm25=1 title=1 hard_slice=1 pack=264/850 r@budget=1 noise=0.88 |
| PASS | `meta/fixture` | cma_v3 corpus_queries=60 |
| PASS | `aggregate/ability_micro_avg` | 1.000 (floor>=0.70) |
| PASS | `aggregate/hard_micro_avg` | 1.000 (floor>=0.55, n=32) |
| PASS | `aggregate/mean_pack_tokens` | 323 (max<=1500, n=42) |
| PASS | `aggregate/recall_at_budget` | 0.833 (floor>=0.80, n=42) |
| PASS | `aggregate/pack_noise` | 0.885 (n=42) |
| PASS | `aggregate/recall_p95_ms` | 13.2ms (target<=800) |
| PASS | `aggregate/pack_p95_ms` | 18.0ms (target<=1200) |
| PASS | `baseline/brain_vs_bm25` | brain=1.000 bm25=0.878 lift=+0.122 n=41 (gate_lift>=-0.05 met=True) |
| PASS | `baseline/brain_vs_title_scan` | brain=1.000 title=0.829 lift=+0.171 n=41 (gate_lift>=-0.05 met=True) |
| PASS | `baseline/hard_slice_brain_vs_bm25` | brain=1.000 bm25=0.545 lift=+0.455 n=11 (floor>=0.15) |
| PASS | `ability/abstention` | 9/9 (100%) |
| PASS | `ability/extraction` | 26/26 (100%) |
| PASS | `ability/knowledge_update` | 5/5 (100%) |
| PASS | `ability/multi_hop` | 10/10 (100%) |
| PASS | `ability/multi_session` | 4/4 (100%) |
| PASS | `ability/procedure` | 4/4 (100%) |
| PASS | `ability/theme_leak` | 2/2 (100%) |

## Methodology notes

- CMA maps LongMemEval *ability language* onto a **coding-agent project brain**
  corpus (neurons + code graph + procedures), not chat-session haystacks.
- Headline metric: **recall@budget** (gold fact in the ≤1500-token pack) + pack noise.
- Ability micro-avg is a **regression gate** (often saturated); quote recall@budget.
- Baselines: **BM25/FTS-only** and naive **title/content token scan** on the same gold.
- Hard subset includes paraphrase, multi-session, and theme-adjacent abstention.
- This is **not** a LongMemEval-S leaderboard claim. See BENCHMARKS.md.
