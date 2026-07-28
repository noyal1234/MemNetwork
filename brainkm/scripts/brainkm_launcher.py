#!/usr/bin/env python3
"""Console entry for brainkm.

macOS marks files inside dot-directories (e.g. .venv) with UF_HIDDEN. Python 3.12+
skips hidden editable-install .pth files, which breaks `from brainkm.cli import app`
in the setuptools-generated script. This launcher registers the editable source
before importing the CLI, and on Darwin clears hidden flags then re-execs once.

When copied into ``.venv/bin/brainkm``, setup/repair rewrite the shebang to the
venv interpreter. As a fallback, if Cursor (or another host) still launches via
``/usr/bin/env python3``, re-exec with the sibling ``.venv/bin/python``.

Hard import failures write ``.brain/cli_health.json`` so SessionStart / doctor
can surface a repair hint (Cursor hook exit codes are otherwise invisible).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

_UF_HIDDEN = 0x8000
_HEAL_ENV = "BRAINKM_LAUNCHER_HEALED"
_CLI_HEALTH = "cli_health.json"
_REPAIR_HINT = "bash brainkm/scripts/repair_venv.sh"


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


def _project_root() -> Path | None:
    """Repo root when this file is ``.venv/bin/brainkm`` or ``scripts/brainkm_launcher.py``."""
    here = Path(__file__).resolve()
    if here.parent.name == "bin" and here.parents[1].name == ".venv":
        return here.parents[2]
    # brainkm/scripts/brainkm_launcher.py → parents[2] = repo root
    if here.parent.name == "scripts" and here.parents[1].name == "brainkm":
        return here.parents[2]
    return None


def _venv_root() -> Path | None:
    here = Path(__file__).resolve()
    if here.parent.name == "bin" and here.parents[1].name == ".venv":
        return here.parents[1]
    root = _project_root()
    if root is not None and (root / ".venv").is_dir():
        return root / ".venv"
    return None


def _write_cli_health(status: str, *, error: str | None = None, cleared_pth: int = 0) -> None:
    root = _project_root()
    if root is None:
        return
    brain = root / ".brain"
    try:
        brain.mkdir(parents=True, exist_ok=True)
        payload = {
            "status": status,
            "at": datetime.now(UTC).isoformat(),
            "error": error,
            "cleared_pth": cleared_pth,
            "fix": _REPAIR_HINT,
        }
        (brain / _CLI_HEALTH).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def _clear_macos_hidden_pth(venv: Path) -> int:
    """Clear UF_HIDDEN on ``*.pth`` under the venv; return how many were flagged."""
    if sys.platform != "darwin":
        return 0
    flagged: list[Path] = []
    for pth in venv.glob("lib/python*/site-packages/*.pth"):
        try:
            flags = getattr(os.stat(pth), "st_flags", 0)
        except OSError:
            continue
        if flags & _UF_HIDDEN:
            flagged.append(pth)
    if not flagged:
        return 0
    for pth in flagged:
        try:
            subprocess.run(
                ["chflags", "nohidden", str(pth)],
                check=False,
                capture_output=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    return len(flagged)


def _drop_broken_brainkm_modules() -> None:
    for key in list(sys.modules):
        if key == "brainkm" or key.startswith("brainkm."):
            del sys.modules[key]


def _bootstrap_editable_source() -> None:
    try:
        import brainkm.cli  # noqa: F401

        return
    except ModuleNotFoundError:
        pass

    # Repo-root cwd (e.g. git hooks) can register a broken namespace package for
    # the outer ``brainkm/`` directory. Drop it before inserting the real src root.
    _drop_broken_brainkm_modules()

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


def _try_import_cli() -> bool:
    try:
        import brainkm.cli  # noqa: F401

        return True
    except ModuleNotFoundError:
        return False


def _heal_and_reexec_if_needed() -> None:
    """Clear macOS hidden .pth flags once, then re-exec so imports see them."""
    if os.environ.get(_HEAL_ENV) == "1":
        return
    venv = _venv_root()
    if venv is None:
        return
    cleared = _clear_macos_hidden_pth(venv)
    if cleared <= 0:
        return
    _write_cli_health("healed", cleared_pth=cleared)
    os.environ[_HEAL_ENV] = "1"
    here = Path(__file__).resolve()
    os.execv(sys.executable, [sys.executable, str(here), *sys.argv[1:]])


def main() -> None:
    _ensure_venv_python()

    # Opportunistic heal: path bootstrap often succeeds while *.pth stay UF_HIDDEN.
    # Clear flags so setuptools/MCP imports keep working, and leave a breadcrumb
    # for SessionStart / doctor (Cursor swallows hook exit codes).
    if os.environ.get(_HEAL_ENV) != "1":
        venv = _venv_root()
        if venv is not None:
            cleared = _clear_macos_hidden_pth(venv)
            if cleared > 0:
                _write_cli_health("healed", cleared_pth=cleared)

    _bootstrap_editable_source()
    if _try_import_cli():
        from brainkm.cli import app

        sys.argv[0] = sys.argv[0].removesuffix(".exe")
        raise SystemExit(app())

    # Import still broken after path bootstrap — try Darwin .pth heal + re-exec.
    _heal_and_reexec_if_needed()
    _drop_broken_brainkm_modules()
    _bootstrap_editable_source()
    if _try_import_cli():
        from brainkm.cli import app

        sys.argv[0] = sys.argv[0].removesuffix(".exe")
        raise SystemExit(app())

    msg = (
        "brainkm CLI import failed (often macOS UF_HIDDEN on .venv *.pth). "
        f"Fix: {_REPAIR_HINT}"
    )
    _write_cli_health("broken", error=msg)
    print(msg, file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
