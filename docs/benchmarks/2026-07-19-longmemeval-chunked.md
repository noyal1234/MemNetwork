# LongMemEval-S — chunked index + fts_primary hybrid (2026-07-19)

Protocol: cleaned LongMemEval-S, `recall_any@K`, sessions chunked (~480 chars, 64 overlap),
ranks aggregated to session ids. Stratified sample: `--stratify 5 --seed 42` (n=30).

| Mode | R@5 | R@10 | P@5 | MRR |
|------|-----|------|-----|-----|
| FTS chunked | **0.867** | 0.900 | 0.311 | 0.689 |
| MiniLM `fts_primary` (vector re-ranks FTS only) | **0.867** | 0.900 | 0.311 | 0.689 |
| naive title/content scan | 0.700 | — | 0.200 | 0.559 |

Side-by-side NDJSON: [2026-07-19-longmemeval-adapters.ndjson](2026-07-19-longmemeval-adapters.ndjson).

Notes:

- Equal RRF hybrid previously collapsed to ~0.37 R@5 on whole-session blobs (128-token MiniLM).
- `fusion_mode=fts_primary` restores the FTS floor; it does **not** yet beat agentmemory’s
  published BM25+vector **0.952** on full-500.
- Full-500 FTS chunked (2026-07-19): **0.908** — [artifact](2026-07-19-longmemeval-s-full.md).
  Pre-chunk blob FTS was **0.934** (2026-07-18).

See [COMPARISON.md](COMPARISON.md).
