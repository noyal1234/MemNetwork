#!/usr/bin/env bash
# Quick repair when brainkm CLI fails with ModuleNotFoundError on macOS.
# Full reset: rm -rf .venv && bash brainkm/scripts/setup_dev.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRAINKM_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$BRAINKM_DIR")"
VENV_DIR="${VENV_DIR:-$PROJECT_ROOT/.venv}"

if [[ ! -d "$VENV_DIR" ]]; then
  echo "No .venv at $VENV_DIR — run: bash brainkm/scripts/setup_dev.sh" >&2
  exit 1
fi

if [[ "$(uname -s)" == "Darwin" ]] && command -v chflags >/dev/null 2>&1; then
  echo "Clearing macOS hidden flags under $VENV_DIR ..."
  chflags -R nohidden "$VENV_DIR" 2>/dev/null || true
  SITE_PACKAGES="$("$VENV_DIR/bin/python" -c 'import site; print(site.getsitepackages()[0])')"
  if compgen -G "$SITE_PACKAGES/*.pth" >/dev/null; then
    chflags nohidden "$SITE_PACKAGES"/*.pth 2>/dev/null || true
  fi
fi

LAUNCHER_SRC="$SCRIPT_DIR/brainkm"
if [[ ! -f "$LAUNCHER_SRC" ]]; then
  LAUNCHER_SRC="$SCRIPT_DIR/brainkm_launcher.py"
fi
BRAINKM_BIN="$VENV_DIR/bin/brainkm"
# Pin shebang to the venv interpreter (Cursor MCP does not activate the venv).
VENV_PYTHON="$("$VENV_DIR/bin/python" -c 'import sys; print(sys.executable)')"
{
  echo "#!$VENV_PYTHON"
  tail -n +2 "$LAUNCHER_SRC"
} >"$BRAINKM_BIN"
chmod +x "$BRAINKM_BIN"

# Stale fallback from older setup_dev runs can error on every Python startup.
SITE_PACKAGES="$("$VENV_DIR/bin/python" -c 'import site; print(site.getsitepackages()[0])')"
rm -f "$SITE_PACKAGES/brainkm-editable.pth"

if ! "$VENV_DIR/bin/brainkm" version >/dev/null 2>&1; then
  echo "Repair incomplete — run: bash brainkm/scripts/setup_dev.sh" >&2
  exit 1
fi

echo "Repaired. brainkm version: $("$VENV_DIR/bin/brainkm" version)"
