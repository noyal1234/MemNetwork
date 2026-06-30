"""Export brain.db neurons to markdown."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from brainkm.db.connection import connect
from brainkm.db.migrate import migrate
from brainkm.db.paths import brain_db_path, brain_dir
from brainkm.services.memory import new_ulid


@dataclass(frozen=True)
class ExportResult:
    path: Path
    neuron_count: int
    full: bool


def export_markdown(
    *,
    project_dir: Path | None = None,
    full: bool = False,
    output: Path | None = None,
) -> ExportResult:
    migrate(project_dir=project_dir, run_integrity_check=False)
    conn = connect(brain_db_path(project_dir))
    try:
        rows = conn.execute(
            """
            SELECT id, kind, subtype, title, content, path, tags, valid_from, valid_until
            FROM nodes
            WHERE valid_until IS NULL OR ?
            ORDER BY kind, subtype, created_at
            """,
            (1 if full else 0,),
        ).fetchall()
    finally:
        conn.close()

    export_dir = brain_dir(project_dir) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    out_path = output or (export_dir / f"EXPORT-{new_ulid()}.md")

    lines = ["# MemNetwork brain export", ""]
    if full:
        lines.append("_Includes archived neurons._")
        lines.append("")

    for row in rows:
        label = row["subtype"] or row["kind"]
        lines.append(f"## {row['title']} ({label})")
        lines.append("")
        lines.append(f"- id: `{row['id']}`")
        if row["path"]:
            lines.append(f"- path: `{row['path']}`")
        if row["tags"]:
            lines.append(f"- tags: {row['tags']}")
        if row["valid_until"]:
            lines.append(f"- archived: {row['valid_until']}")
        lines.append("")
        if row["content"]:
            lines.append(str(row["content"]))
            lines.append("")

    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return ExportResult(path=out_path, neuron_count=len(rows), full=full)
