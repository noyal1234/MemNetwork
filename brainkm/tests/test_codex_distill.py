"""Codex distill adapter: ``codex exec`` vs rules fallback."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from brainkm.adapters.codex_distill import CodexDistillAdapter, resolve_codex_bin
from brainkm.adapters.distill import get_distill_adapter
from brainkm.models.brain_config import BrainConfig
from brainkm.models.distill import TranscriptMessage, TranscriptRound


def _rounds() -> tuple[TranscriptRound, ...]:
    msg = TranscriptMessage(
        role="user",
        text="We chose SQLite FTS5 for the project brain.",
        line_no=1,
    )
    return (TranscriptRound(round_index=0, messages=(msg,)),)


def test_get_distill_adapter_codex_mode() -> None:
    adapter = get_distill_adapter(BrainConfig(capture={"distill_mode": "codex"}))
    assert adapter.mode == "codex"


def test_codex_distill_no_bin_uses_rules() -> None:
    with patch("brainkm.adapters.codex_distill.resolve_codex_bin", return_value=None):
        neurons = CodexDistillAdapter(BrainConfig()).distill_rounds(
            _rounds(),
            round_chunk_ids={0: ["c1"]},
            max_total=5,
        )
    assert isinstance(neurons, list)
    assert len(neurons) >= 1
    assert all(n.chunk_ids == ["c1"] for n in neurons)


def test_codex_distill_fake_exec(tmp_path: Path) -> None:
    fake = MagicMock()
    fake.returncode = 0
    fake.stdout = (
        '[{"subtype":"decision","title":"SQLite brain",'
        '"body":"Use FTS5 for project memory","tags":["sqlite"]}]'
    )
    fake.stderr = ""

    with (
        patch("brainkm.adapters.codex_distill.resolve_codex_bin", return_value="/usr/bin/codex"),
        patch("brainkm.adapters.codex_distill.subprocess.run", return_value=fake) as run,
    ):
        neurons = CodexDistillAdapter(
            BrainConfig(),
            project_dir=tmp_path,
        ).distill_rounds(
            _rounds(),
            round_chunk_ids={0: ["c1"]},
            max_total=5,
        )

    assert len(neurons) == 1
    assert neurons[0].title == "SQLite brain"
    assert neurons[0].subtype == "decision"
    assert neurons[0].chunk_ids == ["c1"]
    assert neurons[0].confidence == 0.85

    cmd = run.call_args.args[0]
    assert cmd[0] == "/usr/bin/codex"
    assert cmd[1] == "exec"
    assert "--sandbox" in cmd and "read-only" in cmd
    assert "--ask-for-approval" in cmd and "never" in cmd
    assert "--ephemeral" in cmd
    assert run.call_args.kwargs["cwd"] == str(tmp_path)


def test_codex_distill_exec_failure_falls_back_to_rules() -> None:
    fake = MagicMock()
    fake.returncode = 1
    fake.stdout = ""
    fake.stderr = "auth failed"

    with (
        patch("brainkm.adapters.codex_distill.resolve_codex_bin", return_value="/usr/bin/codex"),
        patch("brainkm.adapters.codex_distill.subprocess.run", return_value=fake),
    ):
        neurons = CodexDistillAdapter(BrainConfig()).distill_rounds(
            _rounds(),
            round_chunk_ids={0: ["c1"]},
            max_total=5,
        )
    assert len(neurons) >= 1


def test_resolve_codex_bin_which(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "brainkm.adapters.codex_distill.shutil.which",
        lambda _: "/opt/codex",
    )
    assert resolve_codex_bin() == "/opt/codex"
