# LongMemEval-S — dual-grain hybrid sanity (stratified)

- **date:** 2026-07-19
- **mode:** `hybrid-dual-grain` (blob FTS + chunk MiniLM, session-level `fts_primary`)
- **sample:** `--stratify 8 --seed 42` (n=48)
- **log:** [2026-07-19-longmemeval-dual-grain-semantic.log](2026-07-19-longmemeval-dual-grain-semantic.log)

| Metric | hybrid-dual-grain | full-500 fts-blob |
|--------|-------------------|-------------------|
| R@5 | 0.729 | **0.934** |
| R@10 | 0.729 | 0.962 |
| recall@budget | 0.771 | **0.892** |
| mean pack tokens | 314 | 373 |

**Decision:** hybrid did not beat FTS on this sample → skip full-500 `--semantic`.
Default published footnote stays **fts-blob**.
