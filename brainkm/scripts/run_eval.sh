#!/usr/bin/env bash
# Product-grade eval gate — run from repo root after `brainkm install --dev`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

echo "=== brainkm product-grade eval ==="
brainkm bench run eval --project-dir "$ROOT" --profile both

echo ""
echo "=== optional token proxy (compare) ==="
brainkm bench run compare --project-dir "$ROOT" || true

echo ""
echo "Eval complete."
