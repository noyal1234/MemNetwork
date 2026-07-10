#!/usr/bin/env python3
"""Console entry for brainkm.

macOS marks files inside dot-directories (e.g. .venv) with UF_HIDDEN. Python 3.12+
skips hidden editable-install .pth files, which breaks `from brainkm.cli import app`
in the setuptools-generated script. This launcher registers the editable source
before importing the CLI.
"""
from __future__ import annotations

import sys
from pathlib import Path


def _bootstrap_editable_source() -> None:
    try:
        import brainkm.cli  # noqa: F401
        return
    except ModuleNotFoundError:
        pass

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
    _bootstrap_editable_source()
    from brainkm.cli import app

    sys.argv[0] = sys.argv[0].removesuffix(".exe")
    raise SystemExit(app())


if __name__ == "__main__":
    main()
