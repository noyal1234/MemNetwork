"""SQLite WAL checkpoint helpers — confirm durable writes before hook exit."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

from brainkm.logging_config import get_logger

logger = get_logger("db.checkpoint")

# PRAGMA wal_checkpoint busy codes (sqlite3_wal_checkpoint_v2).
_CHECKPOINT_OK = 0
_CHECKPOINT_BUSY = 1
_CHECKPOINT_LOCKED = 2


@dataclass(frozen=True)
class CheckpointResult:
    ok: bool
    busy: int
    log_frames: int
    checkpointed_frames: int
    attempts: int


def wal_checkpoint(
    conn: sqlite3.Connection,
    *,
    mode: str = "FULL",
    max_attempts: int = 10,
    retry_delay_seconds: float = 0.05,
) -> CheckpointResult:
    """Run PRAGMA wal_checkpoint and retry until frames are flushed or attempts exhaust."""
    conn.commit()

    last_busy = _CHECKPOINT_BUSY
    last_log = 0
    last_checkpointed = 0

    for attempt in range(1, max_attempts + 1):
        row = conn.execute(f"PRAGMA wal_checkpoint({mode})").fetchone()
        if row is None:
            break

        last_busy = int(row[0])
        last_log = int(row[1])
        last_checkpointed = int(row[2])

        if last_busy == _CHECKPOINT_OK:
            logger.debug(
                "wal_checkpoint ok mode=%s log=%d checkpointed=%d attempt=%d",
                mode,
                last_log,
                last_checkpointed,
                attempt,
            )
            return CheckpointResult(
                ok=True,
                busy=last_busy,
                log_frames=last_log,
                checkpointed_frames=last_checkpointed,
                attempts=attempt,
            )

        if attempt < max_attempts:
            time.sleep(retry_delay_seconds)

    logger.warning(
        "wal_checkpoint incomplete mode=%s busy=%d log=%d checkpointed=%d attempts=%d",
        mode,
        last_busy,
        last_log,
        last_checkpointed,
        max_attempts,
    )
    return CheckpointResult(
        ok=False,
        busy=last_busy,
        log_frames=last_log,
        checkpointed_frames=last_checkpointed,
        attempts=max_attempts,
    )


def confirm_writes(
    conn: sqlite3.Connection,
    *,
    expected_session_id: str | None = None,
) -> bool:
    """Lightweight post-commit sanity check before hook exit."""
    row = conn.execute("SELECT 1 FROM nodes LIMIT 1").fetchone()
    if row is None and expected_session_id is not None:
        ingested = conn.execute(
            "SELECT neuron_count FROM ingested_sessions WHERE session_id = ?",
            (expected_session_id,),
        ).fetchone()
        if ingested is not None and int(ingested[0]) > 0:
            return False
    return True
