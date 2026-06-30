"""Tests for Cursor hook CLI stdout JSON."""

import json
import shutil
import subprocess
from pathlib import Path


def test_pre_tool_cli_emits_valid_json(tmp_path: Path) -> None:
    brainkm_bin = shutil.which("brainkm")
    if brainkm_bin is None:
        repo_root = Path(__file__).resolve().parents[2]
        brainkm_bin = str(repo_root / ".venv" / "bin" / "brainkm")
    payload = json.dumps({"tool_name": "Shell", "tool_input": {}, "session_id": "cli-test"})
    proc = subprocess.run(
        [
            brainkm_bin,
            "pre-tool",
            "--stdin",
            "--project-dir",
            str(tmp_path),
        ],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data == {"permission": "allow"}
