"""Live git change history joined to commit↔neuron links in the brain.

Git remains the source of truth for commit timelines and diffs. The brain only
supplies sha → session → decision joins recorded by ``git_note``.
"""

from __future__ import annotations

import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from brainkm.models.brain_config import BrainConfig
from brainkm.models.schemas import TruncationManifest
from brainkm.services.budget import BudgetLine, greedy_truncate, line_tokens, priority_for
from brainkm.services.file_history import file_history
from brainkm.services.git_note import COMMIT_KIND
from brainkm.services.memory import token_count


@dataclass(frozen=True)
class LinkedNeuron:
    node_id: str
    kind: str
    subtype: str | None
    title: str


@dataclass(frozen=True)
class CommitTraceEntry:
    git_hash: str
    subject: str
    author_date: str | None
    commit_node_id: str | None = None
    session_id: str | None = None
    linked_neurons: list[LinkedNeuron] = field(default_factory=list)


@dataclass(frozen=True)
class UncommittedSection:
    dirty: bool
    diff_stat: str | None
    agent_touched: bool
    session_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ChangeTraceResult:
    path: str
    commits: list[CommitTraceEntry]
    uncommitted: UncommittedSection
    pack_text: str
    truncation: TruncationManifest
    hint: str | None = None


def _run_git(
    project_dir: Path, *args: str, timeout: float = 15
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=project_dir,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _normalize_path(path: str) -> str:
    return path.strip().lstrip("./")


def git_log_for_path(
    project_dir: Path,
    path: str,
    *,
    limit: int = 10,
) -> list[tuple[str, str, str]]:
    """Return (sha, subject, author_date) newest-first via live git log --follow."""
    proc = _run_git(
        project_dir,
        "log",
        "--follow",
        f"-n{max(1, limit)}",
        "--format=%H%x00%s%x00%aI",
        "--",
        path,
    )
    if proc.returncode != 0:
        return []
    entries: list[tuple[str, str, str]] = []
    for line in (proc.stdout or "").splitlines():
        parts = line.split("\x00")
        if len(parts) < 3:
            continue
        sha, subject, date = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if sha:
            entries.append((sha, subject or "(empty subject)", date))
    return entries


def uncommitted_for_path(
    conn: sqlite3.Connection,
    project_dir: Path,
    path: str,
    *,
    session_id: str | None = None,
) -> UncommittedSection:
    """Working-tree delta + whether session_activity file_seed touched the path."""
    norm = _normalize_path(path)
    status = _run_git(project_dir, "status", "--porcelain", "--", norm)
    dirty = bool((status.stdout or "").strip()) if status.returncode == 0 else False

    diff_stat: str | None = None
    if dirty:
        diff = _run_git(project_dir, "diff", "--stat", "HEAD", "--", norm)
        if diff.returncode == 0 and (diff.stdout or "").strip():
            diff_stat = diff.stdout.strip()
        else:
            # Untracked or staged-only: fall back to name-status.
            named = _run_git(project_dir, "status", "--short", "--", norm)
            if named.returncode == 0 and (named.stdout or "").strip():
                diff_stat = named.stdout.strip()

    base = norm.rsplit("/", 1)[-1]
    rows = conn.execute(
        """
        SELECT DISTINCT session_id FROM session_activity
        WHERE kind = 'file_seed'
          AND (
            tool_name = ?
            OR tool_name LIKE ?
            OR tool_name LIKE ?
          )
        ORDER BY created_at DESC
        LIMIT 5
        """,
        (norm, f"%/{base}", f"%{base}"),
    ).fetchall()
    session_ids = [str(r[0]) for r in rows if r[0]]
    if session_id and session_id in session_ids:
        agent_touched = True
    else:
        agent_touched = bool(session_ids)

    return UncommittedSection(
        dirty=dirty,
        diff_stat=diff_stat,
        agent_touched=agent_touched,
        session_ids=session_ids,
    )


def _commit_node_for_sha(conn: sqlite3.Connection, git_hash: str) -> tuple[str | None, str | None]:
    row = conn.execute(
        """
        SELECT id, session_id FROM nodes
        WHERE kind = ? AND git_hash = ? AND valid_until IS NULL
        LIMIT 1
        """,
        (COMMIT_KIND, git_hash),
    ).fetchone()
    if not row:
        # Prefix match for short hashes
        row = conn.execute(
            """
            SELECT id, session_id FROM nodes
            WHERE kind = ? AND git_hash LIKE ? AND valid_until IS NULL
            LIMIT 1
            """,
            (COMMIT_KIND, f"{git_hash}%"),
        ).fetchone()
    if not row:
        return None, None
    return row[0], row[1]


def _linked_neurons_for_commit(
    conn: sqlite3.Connection,
    commit_id: str,
    *,
    limit: int = 6,
) -> list[LinkedNeuron]:
    rows = conn.execute(
        """
        SELECT n.id, n.kind, n.subtype, n.title
        FROM edges e
        JOIN nodes n ON n.id = e.to_id
        WHERE e.from_id = ?
          AND e.relationship = 'relates_to'
          AND n.valid_until IS NULL
          AND n.kind IN ('memory', 'procedure', 'concept')
        ORDER BY
          CASE n.subtype
            WHEN 'decision' THEN 0
            WHEN 'error' THEN 1
            WHEN 'rule' THEN 2
            ELSE 5
          END,
          COALESCE(n.use_count, 0) DESC,
          n.updated_at DESC
        LIMIT ?
        """,
        (commit_id, limit),
    ).fetchall()
    return [
        LinkedNeuron(
            node_id=row[0],
            kind=row[1],
            subtype=row[2],
            title=row[3],
        )
        for row in rows
    ]


def _fallback_file_neurons(
    conn: sqlite3.Connection,
    path: str,
    *,
    limit: int = 4,
) -> list[LinkedNeuron]:
    _, items = file_history(conn, path, limit=limit)
    return [
        LinkedNeuron(
            node_id=item.node_id,
            kind=item.kind,
            subtype=item.subtype,
            title=item.title,
        )
        for item in items
        if item.kind in ("memory", "procedure", "concept")
    ]


def _format_pack(
    path: str,
    commits: list[CommitTraceEntry],
    uncommitted: UncommittedSection,
) -> str:
    lines = [f"# Change trace: {path}", ""]
    if uncommitted.dirty:
        lines.append("## Uncommitted")
        touch = "yes" if uncommitted.agent_touched else "no"
        lines.append(f"- agent file_seed touch: {touch}")
        if uncommitted.diff_stat:
            lines.append(f"- {uncommitted.diff_stat}")
        lines.append("")
    lines.append("## Commits (live git log)")
    if not commits:
        lines.append("- (no commits for path)")
    for entry in commits:
        short = entry.git_hash[:12]
        why = ""
        if entry.linked_neurons:
            titles = "; ".join(
                f"{n.subtype or n.kind}: {n.title}" for n in entry.linked_neurons[:3]
            )
            why = f" — why: {titles}"
        elif entry.commit_node_id is None:
            why = " — (no brain join)"
        date = f" ({entry.author_date})" if entry.author_date else ""
        lines.append(f"- `{short}`{date} {entry.subject}{why}")
    return "\n".join(lines).strip() + "\n"


def change_trace(
    conn: sqlite3.Connection,
    path: str,
    *,
    project_dir: Path,
    config: BrainConfig,
    limit: int = 10,
    session_id: str | None = None,
) -> ChangeTraceResult:
    """Build a budget-capped change history for ``path``."""
    norm = _normalize_path(path)
    root = project_dir.resolve()
    budget = max(200, config.budget.total_tokens - 50)

    raw_log = git_log_for_path(root, norm, limit=limit)
    hint: str | None = None
    if not raw_log:
        probe = _run_git(root, "rev-parse", "--is-inside-work-tree")
        if probe.returncode != 0:
            hint = "not a git repository; commit timeline unavailable"
        else:
            hint = "no git history for path (new/untracked or rename outside follow window)"

    fallback = _fallback_file_neurons(conn, norm, limit=4)
    commits: list[CommitTraceEntry] = []
    for sha, subject, date in raw_log:
        commit_id, commit_session = _commit_node_for_sha(conn, sha)
        linked: list[LinkedNeuron] = []
        if commit_id:
            linked = _linked_neurons_for_commit(conn, commit_id, limit=4)
        if not linked and fallback:
            # Only attach file-history fallback once (newest commit) to avoid spam.
            if not commits:
                linked = fallback
        commits.append(
            CommitTraceEntry(
                git_hash=sha,
                subject=subject,
                author_date=date or None,
                commit_node_id=commit_id,
                session_id=commit_session,
                linked_neurons=linked,
            )
        )

    uncommitted = uncommitted_for_path(conn, root, norm, session_id=session_id)

    pack = _format_pack(norm, commits, uncommitted)
    lines = [
        BudgetLine(
            node_id="change_trace_pack",
            kind="session",
            subtype=None,
            title=f"trace:{norm}",
            content=pack,
            tokens=line_tokens(f"trace:{norm}", pack),
            priority=priority_for("session", None),
        )
    ]
    included, manifest = greedy_truncate(lines, max_tokens=budget)
    if included:
        pack_text = included[0].content or included[0].title
        # Prefer title+content reconstruction when content was truncated.
        if included[0].content:
            pack_text = included[0].content
        else:
            pack_text = included[0].title
        # Recompute tokens_used accurately
        used = token_count(pack_text)
        manifest = TruncationManifest(
            included_ids=manifest.included_ids,
            omitted_ids=manifest.omitted_ids,
            token_budget=budget,
            tokens_used=used,
        )
    else:
        pack_text = f"# Change trace: {norm}\n(truncated)\n"
        manifest = TruncationManifest(
            omitted_ids=["change_trace_pack"],
            token_budget=budget,
            tokens_used=0,
        )

    return ChangeTraceResult(
        path=norm,
        commits=commits,
        uncommitted=uncommitted,
        pack_text=pack_text,
        truncation=manifest,
        hint=hint,
    )
