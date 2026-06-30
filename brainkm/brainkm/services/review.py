"""V2: Human review queue for auto-captured neurons."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from brainkm.db.paths import brain_dir
from brainkm.services.memory import get_node


@dataclass(frozen=True)
class ReviewItem:
    node_id: str
    title: str
    subtype: str | None
    confidence: float


def pending_dir(project_dir: Path | None = None) -> Path:
    path = brain_dir(project_dir) / "pending"
    path.mkdir(parents=True, exist_ok=True)
    return path


def enqueue_for_review(
    conn: sqlite3.Connection,
    node_id: str,
    *,
    project_dir: Path | None = None,
) -> Path:
    record = get_node(conn, node_id)
    if record is None:
        msg = f"node not found: {node_id}"
        raise ValueError(msg)
    row = conn.execute(
        "SELECT confidence FROM nodes WHERE id = ?",
        (node_id,),
    ).fetchone()
    confidence = float(row["confidence"]) if row else 1.0
    payload = {
        "node_id": node_id,
        "title": record.title,
        "subtype": record.subtype,
        "confidence": confidence,
    }
    out = pending_dir(project_dir) / f"{node_id}.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def list_pending(project_dir: Path | None = None) -> list[ReviewItem]:
    items: list[ReviewItem] = []
    for path in sorted(pending_dir(project_dir).glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        items.append(
            ReviewItem(
                node_id=data["node_id"],
                title=data["title"],
                subtype=data.get("subtype"),
                confidence=float(data.get("confidence", 0.5)),
            )
        )
    return items


def approve_pending(node_id: str, *, project_dir: Path | None = None) -> bool:
    path = pending_dir(project_dir) / f"{node_id}.json"
    if not path.is_file():
        return False
    path.unlink()
    return True
