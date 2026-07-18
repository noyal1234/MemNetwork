#!/usr/bin/env bash
# Common Memory Axes (CMA) — primary public agentic-memory scorecard.
# Run from repo root after `pip install -e ./brainkm`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

# Prefer package import path over outer brainkm/ directory shadowing.
export PYTHONPATH="${ROOT}/brainkm${PYTHONPATH:+:$PYTHONPATH}"

DATE="${CMA_DATE:-$(date +%Y-%m-%d)}"
OUT="${CMA_OUT:-$ROOT/docs/benchmarks/${DATE}-cma.md}"

echo "=== brainkm Common Memory Axes (CMA) ==="
brainkm bench run cma --project-dir "$ROOT" --write-scorecard "$OUT"

echo ""
echo "=== decision vs structure scorecard ==="
brainkm bench run scorecard --project-dir "$ROOT" || true

echo ""
echo "=== LongMemEval-S retrieval footnote (skips if no dataset) ==="
brainkm bench run longmemeval --project-dir "$ROOT" || true

echo ""
echo "CMA scorecard written to: $OUT"
echo "Primary public claim = CMA (abilities + tokens + latency). Not LongMemEval-S QA."
