"""Codex rollout capture — the SessionEnd substitute for a host that cannot run hooks.

Codex has no usable hook delivery path (project .codex/hooks.json is not on a
discovery path; a plugin manifest `hooks` key is rejected by Codex's own
validator), so capture is driven from rollout transcripts instead.
"""

from __future__ import annotations

import json
from pathlib import Path

from brainkm.db.migrate import migrate
from brainkm.models.brain_config import BrainConfig, CaptureConfig
from brainkm.services.codex_rollout import (
    capture_codex_rollouts,
    codex_home,
    iter_rollout_files,
    read_rollout_meta,
    rollouts_for_project,
)


def _rollout_lines(*, session_id: str, cwd: str) -> list[str]:
    return [
        json.dumps(
            {
                "timestamp": "2026-08-01T10:00:00.000Z",
                "type": "session_meta",
                "payload": {
                    "session_id": session_id,
                    "id": session_id,
                    "cwd": cwd,
                    "originator": "codex_cli",
                    "cli_version": "0.146.0",
                },
            }
        ),
        json.dumps(
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "Why did we pick SQLite for the brain?"}
                    ],
                },
            }
        ),
        json.dumps(
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": (
                                "We chose SQLite because the brain must stay local, "
                                "single-file, and survive compaction without a server."
                            ),
                        }
                    ],
                },
            }
        ),
    ]


def _write_rollout(home: Path, *, session_id: str, cwd: str, name: str = "") -> Path:
    day = home / "sessions" / "2026" / "08" / "01"
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"rollout-2026-08-01T10-00-00-{name or session_id}.jsonl"
    path.write_text("\n".join(_rollout_lines(session_id=session_id, cwd=cwd)) + "\n", "utf-8")
    return path


def _config() -> BrainConfig:
    # Rules distill keeps the test hermetic (no external CLI / network).
    return BrainConfig(capture=CaptureConfig(distill_mode="rules"))


def test_codex_home_respects_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "cx"))
    assert codex_home() == tmp_path / "cx"
    monkeypatch.delenv("CODEX_HOME", raising=False)
    assert codex_home() == Path.home() / ".codex"


def test_read_rollout_meta_extracts_cwd_and_session(tmp_path: Path) -> None:
    home = tmp_path / "cx"
    path = _write_rollout(home, session_id="sess-a", cwd="/work/projA")
    meta = read_rollout_meta(path)
    assert meta is not None
    assert meta.session_id == "sess-a"
    assert meta.cwd == Path("/work/projA")
    assert meta.cli_version == "0.146.0"


def test_read_rollout_meta_returns_none_without_session_meta(tmp_path: Path) -> None:
    """A partially written rollout must be skipped, never guessed at."""
    path = tmp_path / "rollout-broken.jsonl"
    path.write_text('{"type":"response_item","payload":{}}\nnot json\n', encoding="utf-8")
    assert read_rollout_meta(path) is None


def test_rollouts_scoped_to_project_by_cwd(tmp_path: Path) -> None:
    """CODEX_HOME is global — capturing everything would pull other projects'
    transcripts into this brain."""
    home = tmp_path / "cx"
    proj = tmp_path / "projA"
    proj.mkdir()
    other = tmp_path / "projB"
    other.mkdir()

    _write_rollout(home, session_id="mine", cwd=str(proj))
    _write_rollout(home, session_id="theirs", cwd=str(other))
    # A nested cwd (agent ran in a subdirectory) still belongs to the project.
    sub = proj / "pkg"
    sub.mkdir()
    _write_rollout(home, session_id="nested", cwd=str(sub))

    assert len(iter_rollout_files(home)) == 3
    found = {m.session_id for m in rollouts_for_project(proj, home=home)}
    assert found == {"mine", "nested"}
    assert "theirs" not in found


def test_capture_dry_run_writes_nothing(tmp_path: Path) -> None:
    home = tmp_path / "cx"
    proj = tmp_path / "projA"
    proj.mkdir()
    migrate(project_dir=proj, run_integrity_check=False)
    _write_rollout(home, session_id="sess-dry", cwd=str(proj))

    result = capture_codex_rollouts(proj, config=_config(), home=home, dry_run=True)
    assert result.matched == 1
    assert result.captured == 0
    assert "sess-dry" in result.captured_sessions


def test_capture_ingests_and_is_duplicate_safe(tmp_path: Path) -> None:
    """Runs from a git hook on every commit, so a second run must be a no-op."""
    home = tmp_path / "cx"
    proj = tmp_path / "projA"
    proj.mkdir()
    migrate(project_dir=proj, run_integrity_check=False)
    _write_rollout(home, session_id="sess-real", cwd=str(proj))

    first = capture_codex_rollouts(proj, config=_config(), home=home)
    assert first.matched == 1
    assert first.captured == 1
    assert not first.errors

    second = capture_codex_rollouts(proj, config=_config(), home=home)
    assert second.matched == 1
    assert second.captured == 0
    assert second.skipped_duplicate == 1


def test_capture_survives_a_corrupt_rollout(tmp_path: Path) -> None:
    """One bad rollout must not stop the rest — a git hook has to stay fail-soft."""
    home = tmp_path / "cx"
    proj = tmp_path / "projA"
    proj.mkdir()
    migrate(project_dir=proj, run_integrity_check=False)
    _write_rollout(home, session_id="good", cwd=str(proj))
    day = home / "sessions" / "2026" / "08" / "01"
    (day / "rollout-2026-08-01T10-00-00-bad.jsonl").write_text("garbage\n", encoding="utf-8")

    result = capture_codex_rollouts(proj, config=_config(), home=home)
    # The corrupt file has no session_meta so it is filtered out before capture.
    assert result.matched == 1
    assert result.captured == 1


def test_capture_no_codex_home_is_noop(tmp_path: Path) -> None:
    proj = tmp_path / "projA"
    proj.mkdir()
    result = capture_codex_rollouts(proj, config=_config(), home=tmp_path / "missing")
    assert result.scanned == 0
    assert result.matched == 0
    assert result.captured == 0


def test_codex_pseudo_session_id_is_stable_and_sanitized(tmp_path: Path) -> None:
    from brainkm.services.codex_rollout import codex_pseudo_session_id

    proj = tmp_path / "My Weird Project!!"
    proj.mkdir()
    sid = codex_pseudo_session_id(proj)
    assert sid == codex_pseudo_session_id(proj)  # stable across calls
    assert sid.startswith("codex-")
    assert all(c.isalnum() or c in "-_" for c in sid)

    other = tmp_path / "other-project"
    other.mkdir()
    assert codex_pseudo_session_id(other) != sid


def _skill_description(text: str) -> str:
    """Extract the YAML `description: >-` block from a rendered skill doc."""
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if l.strip() == "description: >-") + 1
    end = next(i for i in range(start, len(lines)) if lines[i].strip() == "---")
    return " ".join(l.strip() for l in lines[start:end])


def test_context_skill_advertises_session_id_in_description(tmp_path: Path) -> None:
    """Regression: `codex debug prompt-input` proved Codex's model-visible prompt
    shows every skill's name + description unconditionally, but NEVER the body
    unless the model chooses to read the file. A session_id reminder placed only
    in the body is invisible until Codex decides to load this skill — which
    defeats a fix meant to guarantee Codex always has a session_id to pass.
    Without one, brainkm MCP calls that omit session_id fall back to
    hook_session.infer_session_id_if_missing, which can silently attribute
    Codex activity to a DIFFERENT IDE's cached session."""
    from brainkm.services.codex_rollout import codex_pseudo_session_id, sync_codex_context

    proj = tmp_path / "projA"
    proj.mkdir()
    migrate(project_dir=proj, run_integrity_check=False)

    path = sync_codex_context(proj, config=_config())
    assert path is not None
    text = path.read_text(encoding="utf-8")
    expected_sid = codex_pseudo_session_id(proj)

    description = _skill_description(text)
    assert f'session_id="{expected_sid}"' in description
    assert "no SessionStart hook" in description

    # Body carries the same instruction too (reinforcement once Codex does read
    # the file), but description is the one that must never be skipped.
    assert f'session_id="{expected_sid}"' in text


def test_context_skill_session_id_survives_graph_unavailable(tmp_path: Path) -> None:
    """The pack's own 'Pass session_id' reminder only appears when a code graph
    is available (snapshot._graph_status_line). The skill's own instruction
    must not depend on that — a fresh brain with no graph synced yet is the
    common case for a first Codex session."""
    from brainkm.services.codex_rollout import codex_pseudo_session_id, sync_codex_context

    proj = tmp_path / "projA"
    proj.mkdir()
    migrate(project_dir=proj, run_integrity_check=False)  # no graph sync run

    path = sync_codex_context(proj, config=_config())
    assert path is not None
    text = path.read_text(encoding="utf-8")
    assert f'session_id="{codex_pseudo_session_id(proj)}"' in text


def test_render_codex_context_skill_requires_session_id() -> None:
    from brainkm.services.codex_rollout import render_codex_context_skill

    text = render_codex_context_skill("some pack body", session_id="codex-demo")
    assert 'session_id="codex-demo"' in text
    assert "some pack body" in text
    # Must be in the description block, not only the body — see
    # test_context_skill_advertises_session_id_in_description for why.
    assert 'session_id="codex-demo"' in _skill_description(text)


def test_context_skill_written_to_gitignored_codex_dir(tmp_path: Path) -> None:
    """Injection substitute: `.codex/skills/` is a real Codex discovery path and
    `.codex/` is gitignored, so refreshing it every commit costs no repo churn.
    AGENTS.md is deliberately not used — it is tracked."""
    from brainkm.services.codex_rollout import codex_context_skill_path, sync_codex_context

    proj = tmp_path / "projA"
    proj.mkdir()
    migrate(project_dir=proj, run_integrity_check=False)

    path = sync_codex_context(proj, config=_config())
    assert path is not None
    assert path == codex_context_skill_path(proj)
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "name: brainkm-context" in text
    assert "do not edit by hand" in text
    # Must never touch the tracked AGENTS.md.
    assert not (proj / "AGENTS.md").exists()


def test_context_sync_gitignores_itself(tmp_path: Path) -> None:
    """Regression: `.codex/` is NOT gitignored by brainkm's installer. Without an
    explicit entry the regenerated pack shows up as an untracked file on every
    commit — worse than having no pack."""
    from brainkm.services.codex_rollout import sync_codex_context
    from brainkm.services.install import CODEX_CONTEXT_SKILL_IGNORE

    proj = tmp_path / "projA"
    proj.mkdir()
    migrate(project_dir=proj, run_integrity_check=False)

    sync_codex_context(proj, config=_config())
    ignored = (proj / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert CODEX_CONTEXT_SKILL_IGNORE in ignored


def test_context_skill_refreshes_in_place(tmp_path: Path) -> None:
    from brainkm.services.codex_rollout import sync_codex_context

    proj = tmp_path / "projA"
    proj.mkdir()
    migrate(project_dir=proj, run_integrity_check=False)

    first = sync_codex_context(proj, config=_config())
    assert first is not None
    first.write_text("STALE", encoding="utf-8")
    second = sync_codex_context(proj, config=_config())
    assert second == first
    assert "STALE" not in first.read_text(encoding="utf-8")


def test_context_sync_skipped_without_brain(tmp_path: Path) -> None:
    """No brain yet (fresh clone) must be a quiet no-op, not a crash."""
    from brainkm.services.codex_rollout import sync_codex_context

    proj = tmp_path / "projA"
    proj.mkdir()
    assert sync_codex_context(proj, config=_config()) is None


def test_capture_refreshes_context_by_default(tmp_path: Path) -> None:
    home = tmp_path / "cx"
    proj = tmp_path / "projA"
    proj.mkdir()
    migrate(project_dir=proj, run_integrity_check=False)
    _write_rollout(home, session_id="sess-ctx", cwd=str(proj))

    result = capture_codex_rollouts(proj, config=_config(), home=home)
    assert result.context_skill is not None
    assert result.context_skill.is_file()

    off = capture_codex_rollouts(proj, config=_config(), home=home, sync_context=False)
    assert off.context_skill is None


def test_post_commit_hook_runs_codex_capture() -> None:
    """The git hook is the only host-independent trigger that fires after Codex
    does work, since Codex cannot execute brainkm hooks."""
    from brainkm.services.git_note import _hook_snippet

    snippet = _hook_snippet("/opt/brainkm/bin/brainkm")
    assert "codex-capture" in snippet
    assert "--quiet" in snippet
    # Must never break a commit.
    assert snippet.count("|| true") >= 2
