#!/usr/bin/env python3
"""Console entry for brainkm.

macOS marks files inside dot-directories (e.g. .venv) with UF_HIDDEN. Python 3.12+
skips hidden editable-install .pth files, which breaks `from brainkm.cli import app`
in the setuptools-generated script. This launcher registers the editable source
before importing the CLI.

When copied into ``.venv/bin/brainkm``, setup/repair rewrite the shebang to the
venv interpreter. As a fallback, if Cursor (or another host) still launches via
``/usr/bin/env python3``, re-exec with the sibling ``.venv/bin/python``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _ensure_venv_python() -> None:
    """Re-exec with sibling venv python if launched via the wrong interpreter."""
    here = Path(__file__).resolve()
    sibling = here.parent / ("python.exe" if os.name == "nt" else "python")
    if not sibling.is_file():
        return
    expected = sibling.resolve()
    try:
        current = Path(sys.executable).resolve()
    except OSError:
        return
    if current == expected:
        return
    os.execv(str(expected), [str(expected), str(here), *sys.argv[1:]])


def _bootstrap_editable_source() -> None:
    try:
        import brainkm.cli  # noqa: F401
        return
    except ModuleNotFoundError:
        pass

    # Repo-root cwd (e.g. git hooks) can register a broken namespace package for
    # the outer ``brainkm/`` directory. Drop it before inserting the real src root.
    for key in list(sys.modules):
        if key == "brainkm" or key.startswith("brainkm."):
            del sys.modules[key]

    # When installed as .venv/bin/brainkm: parents[2] is the repo root.
    here = Path(__file__).resolve()
    candidates = (
        here.parents[2] / "brainkm",  # .venv/bin/brainkm
        here.parents[1] / "brainkm",  # brainkm/scripts/brainkm_launcher.py
    )
    for src_root in candidates:
        if (src_root / "brainkm").is_dir():
            root = str(src_root)
            if root not in sys.path:
                sys.path.insert(0, root)
            return


def main() -> None:
    _ensure_venv_python()
    _bootstrap_editable_source()
    from brainkm.cli import app

    sys.argv[0] = sys.argv[0].removesuffix(".exe")
    raise SystemExit(app())


if __name__ == "__main__":
    main()
