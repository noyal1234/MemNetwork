"""Per-conversation Antigravity session state (inject throttle, Stop debounce, synthetic precompact)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from brainkm.db.paths import brain_dir

DEFAULT_INJECT_EVERY_N = 8
DEFAULT_STOP_DEBOUNCE_SECONDS = 120
DEFAULT_HANDOVER_MIN_BYTES = 256 * 1024
DEFAULT_HANDOVER_MIN_STEPS = 40
DEFAULT_HANDOVER_MIN_LINES = 200

# Sentinel: fullyIdle key absent from Stop payload (vs present and false).
_MISSING = object()


@dataclass
class AgySessionState:
    conversation_id: str
    last_inject_invocation: int = -1
    last_inject_pack_hash: str = ""
    last_distill_at: float = 0.0
    last_handover_at: float = 0.0
    last_handover_transcript_bytes: int = 0
    transcript_byte_offset: int = 0
    bootstrap_done: bool = False


def resolve_antigravity_project_dir(
    data: dict[str, object] | None = None,
    *,
    explicit: Path | None = None,
    cwd: Path | None = None,
) -> Path:
    """Resolve the real project root for Antigravity hooks.

    Antigravity often runs hook commands with ``cwd`` set to ``<workspace>/.agents``
    (the customization directory). Using bare ``Path.cwd()`` then creates a shadow
    brain at ``.agents/.brain/`` instead of the shared project ``.brain/``.

    Prefer (in order): explicit ``--project-dir``, first ``workspacePaths`` entry
    that already has ``.brain``, any ``workspacePaths`` dir, parent of a ``.agents``
    cwd, then cwd.
    """
    if explicit is not None:
        return explicit.expanduser().resolve()

    cwd_path = (cwd if cwd is not None else Path.cwd()).resolve()

    candidates: list[Path] = []
    if data:
        paths = data.get("workspacePaths") or data.get("workspace_paths")
        if isinstance(paths, list):
            for item in paths:
                if not isinstance(item, str) or not item.strip():
                    continue
                try:
                    path = Path(item.strip()).expanduser().resolve()
                except OSError:
                    continue
                if path.is_dir():
                    candidates.append(path)

    for path in candidates:
        if (path / ".brain").is_dir():
            return path
    if candidates:
        return candidates[0]

    # Hook subprocess cwd is frequently the customization dir itself.
    if cwd_path.name == ".agents":
        return cwd_path.parent

    return cwd_path


def resolve_antigravity_transcript(data: dict[str, object]) -> Path | None:
    """Return an existing transcript path from Stop / PreInvocation stdin."""
    for key in ("transcript_path", "transcriptPath"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            path = Path(value.strip()).expanduser()
            if path.is_file():
                return path

    for key in ("artifactDirectoryPath", "artifact_directory_path"):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        root = Path(value.strip()).expanduser()
        for name in ("transcript.jsonl", "transcript_full.jsonl"):
            path = root / ".system_generated" / "logs" / name
            if path.is_file():
                return path
    return None


def parse_antigravity_stop_gates(data: dict[str, object]) -> tuple[bool, bool]:
    """Return ``(fully_idle, force)`` for Stop distill gating.

    ``fullyIdle`` is required by Antigravity docs; when the key is absent, treat
    completed-turn termination reasons as idle so distill is not silently skipped.
    """
    termination = str(
        data.get("terminationReason") or data.get("termination_reason") or ""
    ).strip()
    termination_l = termination.lower()
    force = termination_l in {"error", "max_steps_exceeded"}

    raw_idle = data.get("fullyIdle", _MISSING)
    if raw_idle is _MISSING:
        raw_idle = data.get("fully_idle", _MISSING)

    if raw_idle is _MISSING:
        # Partial payloads: model finished the turn / no more tools.
        fully_idle = force or termination_l in {"model_stop", "no_tool_call"}
    else:
        fully_idle = bool(raw_idle)

    return fully_idle, force


@dataclass
class AgyHealResult:
    """Outcome of automatic Antigravity wiring repair."""

    hooks_rewritten: bool = False
    shadow_removed: bool = False
    sessions_merged: int = 0

    @property
    def changed(self) -> bool:
        return self.hooks_rewritten or self.shadow_removed or self.sessions_merged > 0


def _merge_agy_session_states(
    primary: dict[str, AgySessionState],
    incoming: dict[str, AgySessionState],
) -> int:
    """Merge ``incoming`` into ``primary``; keep the fresher distill timestamp. Return count added/updated."""
    merged = 0
    for sid, state in incoming.items():
        existing = primary.get(sid)
        if existing is None or state.last_distill_at >= existing.last_distill_at:
            primary[sid] = state
            merged += 1
    return merged


def _write_agy_sessions(project_dir: Path, states: dict[str, AgySessionState]) -> None:
    path = _state_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        sid: {
            "last_inject_invocation": s.last_inject_invocation,
            "last_inject_pack_hash": s.last_inject_pack_hash,
            "last_distill_at": s.last_distill_at,
            "last_handover_at": s.last_handover_at,
            "last_handover_transcript_bytes": s.last_handover_transcript_bytes,
            "transcript_byte_offset": s.transcript_byte_offset,
            "bootstrap_done": s.bootstrap_done,
        }
        for sid, s in states.items()
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def heal_antigravity_wiring(
    project_dir: Path,
    *,
    rewrite_hooks: bool = True,
) -> AgyHealResult:
    """Auto-repair AGY project wiring so users never babysit shadow brains.

    - Rewrites ``.agents/hooks.json`` when ``--project-dir`` is missing.
    - Merges ``agy_sessions.json`` from a shadow ``.agents/.brain`` into the real
      project brain, then removes the shadow directory.
    """
    import shutil

    from brainkm.logging_config import get_logger

    logger = get_logger("services.antigravity_session")
    root = project_dir.expanduser().resolve()
    result = AgyHealResult()
    agents = root / ".agents"
    hooks_path = agents / "hooks.json"
    shadow = agents / ".brain"

    if shadow.is_dir() and (root / ".brain").exists():
        try:
            primary = load_agy_sessions(root)
            shadow_states: dict[str, AgySessionState] = {}
            shadow_path = shadow / "agy_sessions.json"
            if shadow_path.is_file():
                try:
                    raw = json.loads(shadow_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    raw = {}
                if isinstance(raw, dict):
                    for key, value in raw.items():
                        if not isinstance(value, dict):
                            continue
                        shadow_states[str(key)] = AgySessionState(
                            conversation_id=str(key),
                            last_inject_invocation=int(
                                value.get("last_inject_invocation", -1)
                            ),
                            last_inject_pack_hash=str(
                                value.get("last_inject_pack_hash", "")
                            ),
                            last_distill_at=float(value.get("last_distill_at", 0.0)),
                            last_handover_at=float(value.get("last_handover_at", 0.0)),
                            last_handover_transcript_bytes=int(
                                value.get("last_handover_transcript_bytes", 0)
                            ),
                            transcript_byte_offset=int(
                                value.get("transcript_byte_offset", 0)
                            ),
                            bootstrap_done=bool(value.get("bootstrap_done", False)),
                        )
            merged = _merge_agy_session_states(primary, shadow_states)
            if merged:
                _write_agy_sessions(root, primary)
                result.sessions_merged = merged
            shutil.rmtree(shadow)
            result.shadow_removed = True
            logger.info(
                "agy_heal removed shadow brain path=%s merged_sessions=%d",
                shadow,
                result.sessions_merged,
            )
        except Exception:  # noqa: BLE001
            logger.warning("agy_heal failed to remove shadow brain", exc_info=True)

    if rewrite_hooks and hooks_path.is_file():
        try:
            blob = hooks_path.read_text(encoding="utf-8")
        except OSError:
            blob = ""
        needs_rewrite = "brainkm" in blob and (
            "--client antigravity" not in blob or "--project-dir" not in blob
        )
        if needs_rewrite:
            try:
                from brainkm.services.install import (
                    resolve_hook_command,
                    write_antigravity_hooks,
                )

                write_antigravity_hooks(
                    hooks_path,
                    resolve_hook_command(dev=True),
                    project_dir=root,
                )
                result.hooks_rewritten = True
                logger.info(
                    "agy_heal rewritten hooks with --project-dir path=%s", hooks_path
                )
            except Exception:  # noqa: BLE001
                logger.warning("agy_heal failed to rewrite hooks", exc_info=True)

    return result


def _state_path(project_dir: Path | None) -> Path:
    root = project_dir if project_dir is not None else Path.cwd()
    return brain_dir(root) / "agy_sessions.json"


def load_agy_sessions(project_dir: Path | None) -> dict[str, AgySessionState]:
    path = _state_path(project_dir)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, AgySessionState] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        out[str(key)] = AgySessionState(
            conversation_id=str(key),
            last_inject_invocation=int(value.get("last_inject_invocation", -1)),
            last_inject_pack_hash=str(value.get("last_inject_pack_hash", "")),
            last_distill_at=float(value.get("last_distill_at", 0.0)),
            last_handover_at=float(value.get("last_handover_at", 0.0)),
            last_handover_transcript_bytes=int(value.get("last_handover_transcript_bytes", 0)),
            transcript_byte_offset=int(value.get("transcript_byte_offset", 0)),
            bootstrap_done=bool(value.get("bootstrap_done", False)),
        )
    return out


def save_agy_session(project_dir: Path | None, state: AgySessionState) -> None:
    path = _state_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    all_states = load_agy_sessions(project_dir)
    all_states[state.conversation_id] = state
    payload = {
        sid: {
            "last_inject_invocation": s.last_inject_invocation,
            "last_inject_pack_hash": s.last_inject_pack_hash,
            "last_distill_at": s.last_distill_at,
            "last_handover_at": s.last_handover_at,
            "last_handover_transcript_bytes": s.last_handover_transcript_bytes,
            "transcript_byte_offset": s.transcript_byte_offset,
            "bootstrap_done": s.bootstrap_done,
        }
        for sid, s in all_states.items()
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def get_agy_session(project_dir: Path | None, conversation_id: str) -> AgySessionState:
    return load_agy_sessions(project_dir).get(
        conversation_id,
        AgySessionState(conversation_id=conversation_id),
    )


def should_inject_pack(
    state: AgySessionState,
    *,
    invocation_num: int,
    pack_hash: str,
    every_n: int = DEFAULT_INJECT_EVERY_N,
) -> bool:
    if not state.bootstrap_done or invocation_num == 0:
        return True
    if pack_hash and pack_hash != state.last_inject_pack_hash:
        return True
    if every_n > 0 and invocation_num - state.last_inject_invocation >= every_n:
        return True
    return False


def should_run_distill(
    state: AgySessionState,
    *,
    fully_idle: bool,
    debounce_seconds: float = DEFAULT_STOP_DEBOUNCE_SECONDS,
    force: bool = False,
) -> bool:
    if force:
        return True
    if not fully_idle:
        return False
    if state.last_distill_at <= 0:
        return True
    return (time.time() - state.last_distill_at) >= debounce_seconds


def should_synthetic_handover(
    state: AgySessionState,
    *,
    transcript_bytes: int,
    steps: int,
    min_bytes: int = DEFAULT_HANDOVER_MIN_BYTES,
    min_steps: int = DEFAULT_HANDOVER_MIN_STEPS,
) -> bool:
    grew = transcript_bytes - state.last_handover_transcript_bytes
    if transcript_bytes >= min_bytes and grew >= (min_bytes // 4):
        return True
    if steps >= min_steps and state.last_handover_at <= 0:
        return True
    if steps >= min_steps and grew >= 32 * 1024:
        return True
    return False
