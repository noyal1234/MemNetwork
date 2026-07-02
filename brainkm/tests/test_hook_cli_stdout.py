"""Tests for Cursor hook CLI stdout JSON."""

import json
import os
import subprocess
import sys
from pathlib import Path


def test_pre_tool_cli_emits_valid_json(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    package_root = repo_root / "brainkm"
    env = dict(**os.environ)
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{package_root}{os.pathsep}{existing_pythonpath}"
        if existing_pythonpath
        else str(package_root)
    )
    command = [sys.executable, "-m", "brainkm.cli"]
    payload = json.dumps({"tool_name": "Shell", "tool_input": {}, "session_id": "cli-test"})
    proc = subprocess.run(
        [*command, "pre-tool", "--stdin", "--project-dir", str(tmp_path)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data == {"permission": "allow"}
