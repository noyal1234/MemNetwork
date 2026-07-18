# CMA scorecard template

Copy this file to `docs/benchmarks/YYYY-MM-DD-cma.md` or generate it:

```bash
bash brainkm/scripts/run_cma.sh
# or:
brainkm bench run cma --write-scorecard docs/benchmarks/YYYY-MM-DD-cma.md
```

Required metadata in every published scorecard:

- brainkm version (`brainkm version`)
- git commit SHA
- machine / OS
- semantic embeddings on or off
- exact command

Never present CMA results as LongMemEval-S or LoCoMo leaderboard scores.
