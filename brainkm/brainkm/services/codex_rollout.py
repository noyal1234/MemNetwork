"""Codex rollout capture — the SessionEnd substitute for Codex CLI.

Codex cannot run brainkm hooks: project ``.codex/hooks.json`` is not on any
Codex component-discovery path, and a plugin manifest declaring ``hooks`` is
rejected by Codex's own validator (``allowed_keys`` has no ``hooks`` entry in
codex-cli 0.146). So there is no SessionEnd event to hang capture on.

Codex does, however, write a full rollout transcript per session under
``$CODEX_HOME/sessions/<Y>/<M>/<D>/rollout-*.jsonl``, and brainkm already
parses that format (``CODEX_JSONL``). This module locates the rollouts that
belong to a project and feeds them through the normal capture pipeline, so
Codex sessions land in the brain without any host cooperation.

Project scoping comes from the rollout's own ``session_meta`` header, which
records the ``cwd`` Codex ran in — ``$CODEX_HOME`` is global, so capturing
everything would pull other projects' transcripts into this brain.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from brainkm.logging_config import get_logger
from brainkm.models.brain_config import BrainConfig

logger = get_logger("services.codex_rollout")

# Rollout headers are the first line; never read the whole file just to scope it.
_META_SCAN_LINES = 5


def codex_home() -> Path:
    """Resolve ``$CODEX_HOME`` (Codex honours it) falling back to ``~/.codex``."""
    raw = os.environ.get("CODEX_HOME", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".codex"


_SLUG_UNSAFE = "".join(c for c in map(chr, range(0, 128)) if not (c.isalnum() or c in "-_"))
_SLUG_TABLE = str.maketrans({c: "-" for c in _SLUG_UNSAFE})


def codex_pseudo_session_id(project_dir: Path) -> str:
    """Stable, host-neutral session_id for Codex MCP calls.

    Codex never fires SessionStart/UserPromptSubmit (no hook delivery path —
    see module docstring), so nothing ever tells Codex what session_id to use.
    Without one, dispatch_tool's best-effort inference (hook_session.
    infer_session_id_if_missing) falls back to whatever `last_hook_session`
    last cached — which can be a *different IDE's real session* (Cursor,
    Claude) that happened to run more recently, silently misattributing
    Codex's MCP activity to it and corrupting that session's brain_stats and
    procedure learning.

    A fixed, predictable id — advertised to Codex in the context skill body —
    means Codex always has a session_id to pass and never needs the fallback.
    All Codex activity for a project lands in one stable per-project bucket
    rather than per-conversation (Codex assigns its own rollout session_id
    internally, but that value isn't known until after the conversation starts
    and models aren't reliably able to introspect it), which is the right
    tradeoff given hooks cannot supply a real one.
    """
    slug = project_dir.resolve().name.translate(_SLUG_TABLE).strip("-") or "project"
    return f"codex-{slug}"


@dataclass(frozen=True)
class CodexRolloutMeta:
    path: Path
    session_id: str | None
    cwd: Path | None
    originator: str | None = None
    cli_version: str | None = None


def read_rollout_meta(path: Path) -> CodexRolloutMeta | None:
    """Parse the ``session_meta`` header of a rollout file.

    Returns ``None`` when the file is unreadable or carries no session_meta —
    a partially written rollout must be skipped, not guessed at.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for _ in range(_META_SCAN_LINES):
                line = handle.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict) or row.get("type") != "session_meta":
                    continue
                payload = row.get("payload")
                if not isinstance(payload, dict):
                    continue
                cwd_raw = payload.get("cwd")
                cwd = Path(str(cwd_raw)) if cwd_raw else None
                session_id = payload.get("session_id") or payload.get("id")
                return CodexRolloutMeta(
                    path=path,
                    session_id=str(session_id) if session_id else None,
                    cwd=cwd,
                    originator=(
                        str(payload["originator"]) if payload.get("originator") else None
                    ),
                    cli_version=(
                        str(payload["cli_version"]) if payload.get("cli_version") else None
                    ),
                )
    except OSError as exc:
        logger.debug("codex rollout unreadable %s: %s", path, exc)
    return None


def iter_rollout_files(home: Path | None = None) -> list[Path]:
    """All rollout JSONL files, newest first by mtime."""
    root = (home or codex_home()) / "sessions"
    if not root.is_dir():
        return []
    files = [p for p in root.rglob("rollout-*.jsonl") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def _within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except (ValueError, OSError):
        return False
    return True


def rollouts_for_project(
    project_dir: Path,
    *,
    home: Path | None = None,
    limit: int | None = None,
) -> list[CodexRolloutMeta]:
    """Rollouts whose recorded ``cwd`` is the project root or inside it."""
    root = project_dir.resolve()
    out: list[CodexRolloutMeta] = []
    for path in iter_rollout_files(home):
        meta = read_rollout_meta(path)
        if meta is None or meta.cwd is None:
            continue
        if not _within(meta.cwd, root):
            continue
        out.append(meta)
        if limit is not None and len(out) >= limit:
            break
    return out


# Generated skill that carries the memory pack to Codex. `.codex/skills/` is a
# real Codex discovery path (unlike `.codex/hooks.json`) *and* `.codex/` is
# gitignored, so refreshing this on every commit costs no repo churn. AGENTS.md
# is deliberately NOT used: it is tracked, and there is a standing project
# decision to keep it tracked, so writing a live pack there would dirty the
# working tree on every commit.
CONTEXT_SKILL_NAME = "brainkm-context"


def _context_skill_description(session_id: str) -> str:
    """Skill description text.

    The session_id reminder MUST live here, not in the skill body: verified
    with ``codex debug prompt-input`` that Codex's model-visible prompt lists
    every skill's name + description unconditionally, but never its body
    unless the model chooses to read the file (skills are a pull, not a
    push — see sync_codex_context). A body-only reminder is invisible until
    Codex decides to load this skill, which defeats the point of a fix meant
    to guarantee Codex always has a session_id to pass.
    """
    return (
        "Current project memory from brainkm: recent architecture decisions, rules, "
        "and known failures for this repository. Load this before answering why the "
        "code is the way it is, before changing unfamiliar code, or when a question "
        "depends on past decisions. This is a frozen snapshot — for live answers call "
        "the brainkm MCP tools (recall, traverse, context_pack, trace_changes). "
        f'Pass session_id="{session_id}" on every brainkm MCP call — Codex has no '
        "SessionStart hook to supply one otherwise, and omitting it silently "
        "attributes your activity to a different tool's session."
    )


def codex_context_skill_path(project_dir: Path) -> Path:
    return project_dir / ".codex" / "skills" / CONTEXT_SKILL_NAME / "SKILL.md"


def render_codex_context_skill(pack_text: str, *, session_id: str) -> str:
    """Render the memory pack as a Codex skill document.

    ``session_id`` is stated in the *description* (see
    ``_context_skill_description``) as well as the body, so it reaches Codex
    even if the model never opens this file.
    """
    body = pack_text.strip() or "_No durable project memory captured yet._"
    return (
        "---\n"
        f"name: {CONTEXT_SKILL_NAME}\n"
        "description: >-\n"
        + "".join(f"  {line}\n" for line in _wrap_description(session_id))
        + "---\n\n"
        "# brainkm project memory\n\n"
        "Generated by `brainkm codex-capture` — do not edit by hand; edits are\n"
        "overwritten on the next refresh. brainkm adds this path to .gitignore so\n"
        "the regenerated pack does not churn the repo.\n\n"
        f'**Pass `session_id="{session_id}"` on every brainkm MCP call** (recall, '
        "traverse, context_pack, trace_changes, remember, feedback, brain_stats). "
        "Codex has no SessionStart hook, so nothing else supplies a session_id — "
        "omitting it silently attributes your activity to a different tool's "
        "session.\n\n"
        f"{body}\n"
    )


def _wrap_description(session_id: str, *, width: int = 88) -> list[str]:
    words = _context_skill_description(session_id).split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def sync_codex_context(
    project_dir: Path,
    *,
    config: BrainConfig | None = None,
) -> Path | None:
    """Write the current memory pack into a Codex-discoverable skill.

    This is the injection substitute for a host that cannot run SessionStart:
    Codex always sees the skill's *description* and can pull the body on demand.
    It is a pull, not a push — weaker than a real hook, but the only mechanism
    Codex actually honours.
    """
    from brainkm.db.connection import connect
    from brainkm.db.paths import brain_db_path
    from brainkm.services.config_loader import load_brain_config
    from brainkm.services.snapshot import build_frozen_snapshot

    cfg = config or load_brain_config(project_dir)
    if not cfg.injection.frozen_snapshot:
        return None

    db = brain_db_path(project_dir)
    if not db.is_file():
        return None

    try:
        conn = connect(db)
    except Exception as exc:  # noqa: BLE001
        logger.warning("codex context sync: cannot open brain: %s", exc)
        return None
    session_id = codex_pseudo_session_id(project_dir)
    try:
        snapshot = build_frozen_snapshot(
            conn,
            session_id,
            cfg,
            force=True,
            client="codex",
        )
        conn.commit()
    except Exception as exc:  # noqa: BLE001 - never break the caller (git hook)
        logger.warning("codex context sync failed: %s", exc)
        return None
    finally:
        conn.close()

    # This runs outside `install` (git hook / manual), so it cannot rely on the
    # installer having added the ignore entry — a regenerated pack showing up as
    # an untracked file on every commit would be worse than no pack at all.
    try:
        from brainkm.services.install import (
            CODEX_CONTEXT_SKILL_IGNORE,
            _ensure_gitignore_entry,
        )

        _ensure_gitignore_entry(project_dir, CODEX_CONTEXT_SKILL_IGNORE)
    except Exception as exc:  # noqa: BLE001 - ignore-file hygiene is best-effort
        logger.debug("codex context gitignore entry skipped: %s", exc)

    path = codex_context_skill_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_codex_context_skill(snapshot.pack_text or "", session_id=session_id),
        encoding="utf-8",
    )
    logger.info("codex context skill written: %s", path)
    return path


@dataclass
class CodexCaptureResult:
    scanned: int = 0
    matched: int = 0
    captured: int = 0
    skipped_duplicate: int = 0
    neuron_count: int = 0
    errors: list[str] = field(default_factory=list)
    captured_sessions: list[str] = field(default_factory=list)
    context_skill: Path | None = None


def capture_codex_rollouts(
    project_dir: Path,
    *,
    config: BrainConfig | None = None,
    home: Path | None = None,
    limit: int | None = 20,
    dry_run: bool = False,
    distill_timeout_seconds: int | None = None,
    sync_context: bool = True,
) -> CodexCaptureResult:
    """Capture this project's Codex rollouts into the brain.

    Duplicate suppression is the normal transcript fingerprint check inside
    ``capture_transcript_file``, so this is safe to run repeatedly (e.g. from a
    git hook on every commit): only genuinely new content is distilled.
    """
    from brainkm.services.capture import capture_transcript_file

    result = CodexCaptureResult()
    all_files = iter_rollout_files(home)
    result.scanned = len(all_files)

    metas = rollouts_for_project(project_dir, home=home, limit=limit)
    result.matched = len(metas)
    if dry_run:
        result.captured_sessions = [m.session_id or m.path.name for m in metas]
        return result

    for meta in metas:
        try:
            captured = capture_transcript_file(
                meta.path,
                project_dir=project_dir,
                config=config,
                session_id=meta.session_id,
                skip_duplicate=True,
                distill_timeout_seconds=distill_timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001 - one bad rollout must not stop the rest
            logger.warning("codex rollout capture failed %s: %s", meta.path.name, exc)
            result.errors.append(f"{meta.path.name}: {exc}")
            continue
        if captured.skipped:
            if captured.reason == "duplicate fingerprint":
                result.skipped_duplicate += 1
            continue
        result.captured += 1
        result.neuron_count += captured.neuron_count
        if captured.session_id:
            result.captured_sessions.append(captured.session_id)

    # Refresh the injection substitute after capture, so the pack Codex can pull
    # already includes whatever this run just learned.
    if sync_context:
        try:
            result.context_skill = sync_codex_context(project_dir, config=config)
        except Exception as exc:  # noqa: BLE001 - context is best-effort
            logger.warning("codex context sync failed: %s", exc)
            result.errors.append(f"context sync: {exc}")

    logger.info(
        "codex rollout capture project=%s scanned=%d matched=%d captured=%d dup=%d neurons=%d",
        project_dir,
        result.scanned,
        result.matched,
        result.captured,
        result.skipped_duplicate,
        result.neuron_count,
    )
    return result
