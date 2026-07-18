"""Git-shareable team neuron layer and git metadata linking."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from brainkm.db.connection import connect
from brainkm.db.paths import brain_db_path, brain_dir
from brainkm.logging_config import get_logger
from brainkm.models.brain_config import BrainConfig
from brainkm.services.export import export_markdown

logger = get_logger("services.team")


def team_dir(project_dir: Path, config: BrainConfig | None = None) -> Path:
    cfg = config or BrainConfig()
    return brain_dir(project_dir) / cfg.team.team_dir


def export_team_neurons(project_dir: Path, *, config: BrainConfig | None = None) -> Path:
    """Export active memory neurons to `.brain/team/neurons.json` (deterministic)."""
    dest_dir = team_dir(project_dir, config)
    dest_dir.mkdir(parents=True, exist_ok=True)
    db = brain_db_path(project_dir)
    conn = connect(db)
    try:
        rows = conn.execute(
            """
            SELECT id, kind, subtype, title, content, tags, confidence, source
            FROM nodes
            WHERE kind = 'memory' AND valid_until IS NULL AND user_pinned = 1
            ORDER BY id ASC
            """
        ).fetchall()
        # Fall back to high-confidence decisions/rules when nothing pinned.
        if not rows:
            rows = conn.execute(
                """
                SELECT id, kind, subtype, title, content, tags, confidence, source
                FROM nodes
                WHERE kind = 'memory' AND valid_until IS NULL
                  AND subtype IN ('decision', 'rule')
                  AND confidence >= 0.85
                ORDER BY id ASC
                LIMIT 100
                """
            ).fetchall()
        payload = []
        for row in rows:
            tags = []
            try:
                tags = json.loads(row[5] or "[]")
            except json.JSONDecodeError:
                tags = []
            payload.append(
                {
                    "id": row[0],
                    "kind": row[1],
                    "subtype": row[2],
                    "title": row[3],
                    "content": row[4],
                    "tags": tags,
                    "confidence": row[6],
                    "source": row[7],
                }
            )
        out = dest_dir / "neurons.json"
        out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return out
    finally:
        conn.close()


def import_team_neurons(project_dir: Path, *, config: BrainConfig | None = None) -> int:
    """Import `.brain/team/neurons.json` via confidence-based merge. Returns imported count."""
    path = team_dir(project_dir, config) / "neurons.json"
    if not path.is_file():
        return 0
    raw = json.loads(path.read_text(encoding="utf-8"))
    records = raw if isinstance(raw, list) else raw.get("neurons", [])
    # Tag team-sourced neurons for diversify/budget.
    for item in records:
        if isinstance(item, dict):
            tags = item.get("tags") if isinstance(item.get("tags"), list) else []
            tags = [str(t) for t in tags]
            if "team:" not in tags and "team" not in tags:
                tags.append("team:")
            item["tags"] = tags
    from brainkm.services.import_merge import import_neurons_merge
    from brainkm.db.connection import connect
    from brainkm.db.migrate import migrate
    from brainkm.db.paths import brain_db_path

    migrate(project_dir=project_dir, run_integrity_check=False)
    conn = connect(brain_db_path(project_dir))
    try:
        result = import_neurons_merge(conn, records if isinstance(records, list) else [])
        conn.commit()
    finally:
        conn.close()
    logger.info("team import: imported=%s skipped=%s", result.imported, result.skipped)
    return result.imported


def current_git_metadata(project_dir: Path) -> tuple[str | None, str | None]:
    """Return (git_hash, git_branch) or (None, None)."""
    try:
        hash_p = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        branch_p = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        git_hash = hash_p.stdout.strip() if hash_p.returncode == 0 else None
        branch = branch_p.stdout.strip() if branch_p.returncode == 0 else None
        return git_hash or None, branch or None
    except (OSError, subprocess.SubprocessError):
        return None, None


def stamp_git_on_recent(
    conn,
    *,
    project_dir: Path,
    session_id: str | None,
    limit: int = 50,
) -> int:
    """Attach current git hash/branch to recent session neurons missing metadata."""
    git_hash, branch = current_git_metadata(project_dir)
    if not git_hash:
        return 0
    if session_id:
        cur = conn.execute(
            """
            UPDATE nodes
            SET git_hash = COALESCE(git_hash, ?),
                git_branch = COALESCE(git_branch, ?)
            WHERE session_id = ? AND kind = 'memory' AND git_hash IS NULL
            """,
            (git_hash, branch, session_id),
        )
        return int(cur.rowcount or 0)

    rows = conn.execute(
        """
        SELECT id FROM nodes
        WHERE kind = 'memory' AND git_hash IS NULL AND valid_until IS NULL
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    updated = 0
    for (node_id,) in rows:
        conn.execute(
            """
            UPDATE nodes
            SET git_hash = COALESCE(git_hash, ?),
                git_branch = COALESCE(git_branch, ?)
            WHERE id = ?
            """,
            (git_hash, branch, node_id),
        )
        updated += 1
    return updated



# Re-export for callers that expect markdown exports alongside team JSON.
__all__ = [
    "export_team_neurons",
    "import_team_neurons",
    "current_git_metadata",
    "stamp_git_on_recent",
    "team_dir",
    "export_markdown",
]
