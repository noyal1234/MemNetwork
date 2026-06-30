#!/usr/bin/env bash
# Install brainkm into repo-root .venv (never system Python).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRAINKM_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$BRAINKM_DIR")"
VENV_DIR="${VENV_DIR:-$PROJECT_ROOT/.venv}"

if [[ ! -d "$VENV_DIR" ]]; then
  echo "Creating virtual environment at $VENV_DIR ..."
  PYTHON_BIN=""
  for candidate in python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
  if [[ -z "$PYTHON_BIN" ]]; then
    echo "ERROR: python3 not found. Install Python 3.11+." >&2
    exit 1
  fi
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

PYTHON="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

echo "Using: $($PYTHON --version)"
PY_MINOR="$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "$PY_MINOR" == "3.14" ]] || [[ "$PY_MINOR" > "3.12" ]]; then
  echo "WARNING: Python $PY_MINOR detected. Prefer 3.11 or 3.12 for brainkm deps." >&2
  echo "  Recreate venv: rm -rf \"$VENV_DIR\" && bash \"$SCRIPT_DIR/setup_dev.sh\"" >&2
fi

echo "Installing editable brainkm[dev] from $BRAINKM_DIR ..."

"$PIP" install --upgrade pip setuptools wheel
"$PIP" install -e "$BRAINKM_DIR[dev,graphify]"

SITE_PACKAGES="$("$PYTHON" -c 'import site; print(site.getsitepackages()[0])')"

# macOS marks dot-directories (e.g. .venv) UF_HIDDEN; Python 3.12+ skips hidden .pth
# files, which breaks editable installs silently. Clear the flag after every install.
if [[ "$(uname -s)" == "Darwin" ]] && command -v chflags >/dev/null 2>&1; then
  chflags -R nohidden "$VENV_DIR" 2>/dev/null || true
  if compgen -G "$SITE_PACKAGES/*.pth" >/dev/null; then
    chflags nohidden "$SITE_PACKAGES"/*.pth 2>/dev/null || true
  fi
fi

# Fallback: non-hidden pth that registers the setuptools editable finder.
PTH_FILE="$SITE_PACKAGES/brainkm-editable.pth"
FINDER="$SITE_PACKAGES/__editable___brainkm_0_1_0_finder.py"
if [[ -f "$FINDER" ]]; then
  printf '%s\n' "import __editable___brainkm_0_1_0_finder; __editable___brainkm_0_1_0_finder.install()" > "$PTH_FILE"
  if [[ "$(uname -s)" == "Darwin" ]] && command -v chflags >/dev/null 2>&1; then
    chflags nohidden "$PTH_FILE" 2>/dev/null || true
  fi
fi

if ! "$PYTHON" -c "import brainkm.cli" 2>/dev/null; then
  echo "ERROR: brainkm editable install failed." >&2
  echo "  On macOS, ensure .venv is not hidden: chflags -R nohidden \"$VENV_DIR\"" >&2
  echo "  Or recreate: rm -rf \"$VENV_DIR\" && bash \"$SCRIPT_DIR/setup_dev.sh\"" >&2
  exit 1
fi

echo ""
echo "Done. Activate with:"
echo "  source \"$VENV_DIR/bin/activate\""
echo ""
echo "Next steps:"
echo "  brainkm install --dev    # MCP, hooks, brainkm.mdc, .brain/"
echo "  brainkm graph sync       # optional first code graph"
echo ""
echo "Verify:"
echo "  brainkm version"
"$VENV_DIR/bin/brainkm" version
