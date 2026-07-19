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
