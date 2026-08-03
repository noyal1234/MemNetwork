"""Headroom contract for endtask_memory_v1.

endtask_v1 cannot discriminate on a memory-enabled arm: its questions are about
brainkm's own configuration inside the brainkm repo, so the no-memory arm answers
them with a single ripgrep. See docs/benchmarks/2026-08-02-endtask-codex-core.md.

endtask_memory_v1 fixes that by construction: every answer lives only in a seeded
neuron. This module is what keeps that true — if an answer ever leaks into the
working tree, the corresponding task silently stops measuring memory, and these
tests fail instead.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = (
    REPO_ROOT / "brainkm" / "brainkm" / "bench" / "fixtures" / "endtask_memory_v1.json"
)

# The fixture and past scorecards contain the answers by construction. What must
# stay clean is the code the agent can actually search during a run.
EXCLUDED_DIRS = {
    ".brain",
    ".git",
    "benchmarks",
    "fixtures",
    "build",
    "__pycache__",
    ".venv",
    "node_modules",
    ".pytest_cache",
    ".ruff_cache",
    # Generated caches/artifacts, not source an agent would mine for a decision.
    # stat-index.json in particular is a bag of numbers that collides with any
    # bare numeric answer token by coincidence.
    "graphify-out",
}
EXCLUDED_FILES = {"brainkm/tests/test_endtask_memory_fixture.py"}
BINARY_SUFFIXES = {
    ".db",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".pdf",
    ".zip",
    ".gz",
    ".whl",
    ".so",
    ".dylib",
    ".pyc",
    ".html",  # generated pytest/textual snapshot reports
}


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _task_ids() -> list[str]:
    return [t["id"] for t in _fixture()["tasks"]]


def test_fixture_parses_and_core_tier_is_six() -> None:
    fx = _fixture()
    assert fx["id"] == "endtask_memory_v1"
    core = fx["core_task_ids"]
    assert len(core) == 6, "core tier must stay 6 tasks for cross-fixture comparability"
    known = set(_task_ids())
    assert set(core) <= known, f"core references unknown tasks: {set(core) - known}"


def test_core_tier_mixes_knowledge_and_change() -> None:
    fx = _fixture()
    by_id = {t["id"]: t for t in fx["tasks"]}
    classes = {by_id[t]["class"] for t in fx["core_task_ids"]}
    assert classes == {"knowledge", "change"}, (
        "core must exercise both recall and edit-under-memory, like endtask_v1 core"
    )


def test_every_task_declares_a_headroom_check() -> None:
    for task in _fixture()["tasks"]:
        assert task.get("headroom_check"), (
            f"{task['id']} has no headroom_check — it cannot be shown to be memory-only"
        )


def _search_worktree(pattern: str) -> list[str]:
    """Repo-relative paths whose text matches `pattern`, honouring EXCLUDED_DIRS.

    Done in Python rather than shelling out to ripgrep so the headroom contract
    holds on any machine — a skipped check here would silently retire the only
    guarantee this fixture rests on.
    """
    rx = re.compile(pattern, re.IGNORECASE)
    hits: list[str] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(REPO_ROOT)
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        if rel.as_posix() in EXCLUDED_FILES:
            continue
        if path.suffix in BINARY_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if rx.search(text):
            hits.append(rel.as_posix())
    return hits


@pytest.mark.parametrize("task_id", _task_ids())
def test_answer_is_not_recoverable_from_the_worktree(task_id: str) -> None:
    """The whole point: searching the answer must come up empty for the no-memory arm.

    A match here means the fact leaked into the repo and the task now measures
    grep, not memory — exactly the endtask_v1 failure mode.
    """
    task = next(t for t in _fixture()["tasks"] if t["id"] == task_id)
    pattern = task["headroom_check"]
    hits = _search_worktree(pattern)
    assert not hits, (
        f"{task_id}: answer pattern {pattern!r} is findable in the worktree "
        f"({hits[:5]}). The no-memory arm can now recover it without the brain, "
        f"so this task no longer measures memory. Change the seeded fact or "
        f"remove the leak."
    )


def test_change_tasks_target_a_real_file() -> None:
    """Change-class checkers must point at a file that exists, or they pass vacuously."""
    for task in _fixture()["tasks"]:
        if task["class"] != "change":
            continue
        cmd = task["grade"]["command"]
        # crude but sufficient: pull the trailing path argument off the rg command
        path = cmd.split()[-1]
        assert (REPO_ROOT / path).is_file(), f"{task['id']} checks missing file {path}"
