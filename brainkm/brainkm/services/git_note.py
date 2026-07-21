"""Record a git commit as a brain join node (sha → session → neurons / files).

Diffs are never stored — only metadata git cannot know. Live history comes from
``git log`` / ``git diff`` at trace time (see ``change_trace``).
"""

from __future__ import annotations

import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from shlex import quote

from brainkm.logging_config import get_logger
from brainkm.services.audit import utc_now_iso
from brainkm.services.memory import create_neuron, new_ulid
from brainkm.services.team import current_git_metadata

logger = get_logger("services.git_note")

COMMIT_KIND = "commit"
COMMIT_SUBTYPE = "git"
SESSION_LOOKBACK_HOURS = 48
MAX_SESSION_NEURONS = 40
MAX_FILES_IN_CONTENT = 40
HOOK_MARKER = "# brainkm-commit-trace"


@dataclass(frozen=True)
class GitNoteResult:
    commit_id: str | None
    git_hash: str
    created: bool
    files_linked: int
    neurons_linked: int
    session_id: str | None
    subject: str
    skipped: bool = False
    skip_reason: str | None = None


@dataclass(frozen=True)
class HookInstallResult:
    path: Path | None
    installed: bool
    skipped: bool
    warnings: tuple[str, ...] = ()
    appended_to_existing: bool = False


def _run_git(project_dir: Path, *args: str, timeout: float = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=project_dir,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _insert_edge(
    conn: sqlite3.Connection,
    *,
    from_id: str,
    to_id: str,
    relationship: str,
    weight: float,
) -> None:
    now = utc_now_iso()
    conn.execute(
        """
        INSERT OR IGNORE INTO edges (id, from_id, to_id, relationship, weight, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (new_ulid(), from_id, to_id, relationship, weight, now, now),
    )


def _resolve_code_file_id(conn: sqlite3.Connection, path: str) -> str | None:
    from brainkm.services.file_history import resolve_code_node_for_path

    return resolve_code_node_for_path(conn, path)


def commit_subject(project_dir: Path, git_hash: str | None = None) -> str:
    rev = git_hash or "HEAD"
    proc = _run_git(project_dir, "log", "-1", "--format=%s", rev)
    if proc.returncode != 0:
        return "(unknown commit)"
    return (proc.stdout or "").strip() or "(empty subject)"


def commit_files(project_dir: Path, git_hash: str | None = None) -> list[str]:
    rev = git_hash or "HEAD"
    # --root includes the initial commit (no parent); without it, files are empty.
    proc = _run_git(
        project_dir,
        "diff-tree",
        "--no-commit-id",
        "--name-only",
        "-r",
        "--root",
        rev,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]


def is_merge_commit(project_dir: Path, git_hash: str | None = None) -> bool:
    rev = git_hash or "HEAD"
    proc = _run_git(project_dir, "rev-list", "--parents", "-n", "1", rev)
    if proc.returncode != 0:
        return False
    parts = (proc.stdout or "").strip().split()
    # sha + >1 parent ⇒ merge
    return len(parts) > 2


def resolve_session_for_commit(
    conn: sqlite3.Connection,
    *,
    files: list[str],
    session_id: str | None = None,
) -> str | None:
    """Pick the session that most likely produced this commit."""
    if session_id:
        return session_id

    cutoff = (
        datetime.now(UTC) - timedelta(hours=SESSION_LOOKBACK_HOURS)
    ).isoformat()

    if files:
        placeholders = ",".join("?" for _ in files)
        row = conn.execute(
            f"""
            SELECT session_id, COUNT(*) AS hits
            FROM session_activity
            WHERE kind = 'file_seed'
              AND tool_name IN ({placeholders})
              AND created_at >= ?
            GROUP BY session_id
            ORDER BY hits DESC, MAX(created_at) DESC
            LIMIT 1
            """,
            (*files, cutoff),
        ).fetchone()
        if row and row[0]:
            return str(row[0])

    row = conn.execute(
        """
        SELECT session_id FROM session_activity
        WHERE created_at >= ?
          AND session_id IS NOT NULL
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (cutoff,),
    ).fetchone()
    if row and row[0]:
        return str(row[0])

    row = conn.execute(
        """
        SELECT session_id FROM nodes
        WHERE kind = 'memory'
          AND session_id IS NOT NULL
          AND valid_until IS NULL
        ORDER BY created_at DESC
        LIMIT 1
        """
    ).fetchone()
    return str(row[0]) if row and row[0] else None


def _find_commit_node(conn: sqlite3.Connection, git_hash: str) -> str | None:
    row = conn.execute(
        """
        SELECT id FROM nodes
        WHERE kind = ? AND git_hash = ? AND valid_until IS NULL
        LIMIT 1
        """,
        (COMMIT_KIND, git_hash),
    ).fetchone()
    return row[0] if row else None


def _file_linked_neuron_ids(
    conn: sqlite3.Connection,
    *,
    files: list[str],
    session_id: str | None,
) -> list[str]:
    """Prefer memories that already about_file the commit's code nodes."""
    if not files:
        return []
    code_ids: list[str] = []
    for path in files:
        code_id = _resolve_code_file_id(conn, path)
        if code_id and code_id not in code_ids:
            code_ids.append(code_id)
    if not code_ids:
        return []
    placeholders = ",".join("?" for _ in code_ids)
    params: list[object] = list(code_ids)
    session_clause = ""
    if session_id:
        session_clause = "AND n.session_id = ?"
        params.append(session_id)
    params.append(MAX_SESSION_NEURONS)
    rows = conn.execute(
        f"""
        SELECT DISTINCT n.id
        FROM edges e
        JOIN nodes n ON n.id = e.from_id
        WHERE e.to_id IN ({placeholders})
          AND e.relationship IN ('about_file', 'about_symbol')
          AND n.kind = 'memory'
          AND n.valid_until IS NULL
          {session_clause}
        ORDER BY COALESCE(n.use_count, 0) DESC, n.updated_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [row[0] for row in rows]


def _session_neuron_ids(conn: sqlite3.Connection, session_id: str | None) -> list[str]:
    if not session_id:
        return []
    rows = conn.execute(
        """
        SELECT id FROM nodes
        WHERE kind = 'memory'
          AND session_id = ?
          AND valid_until IS NULL
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (session_id, MAX_SESSION_NEURONS),
    ).fetchall()
    return [row[0] for row in rows]


def _neurons_to_link(
    conn: sqlite3.Connection,
    *,
    files: list[str],
    session_id: str | None,
) -> list[str]:
    linked = _file_linked_neuron_ids(conn, files=files, session_id=session_id)
    if linked:
        return linked
    return _session_neuron_ids(conn, session_id)


def note_commit(
    conn: sqlite3.Connection,
    *,
    project_dir: Path,
    git_hash: str | None = None,
    session_id: str | None = None,
) -> GitNoteResult | None:
    """Upsert a commit node and link touched files + session neurons.

    Skips merge commits and commits with no files (no-op result, not None).
    """
    root = project_dir.resolve()
    head_hash, branch = current_git_metadata(root)
    sha = (git_hash or head_hash or "").strip()
    if not sha:
        logger.warning("git-note: no HEAD in %s", root)
        return None

    subject = commit_subject(root, sha)
    if is_merge_commit(root, sha):
        logger.info("git-note skip merge sha=%s", sha[:12])
        return GitNoteResult(
            commit_id=None,
            git_hash=sha,
            created=False,
            files_linked=0,
            neurons_linked=0,
            session_id=None,
            subject=subject,
            skipped=True,
            skip_reason="merge",
        )

    files = commit_files(root, sha)
    if not files:
        logger.info("git-note skip empty sha=%s", sha[:12])
        return GitNoteResult(
            commit_id=None,
            git_hash=sha,
            created=False,
            files_linked=0,
            neurons_linked=0,
            session_id=None,
            subject=subject,
            skipped=True,
            skip_reason="empty",
        )

    resolved_session = resolve_session_for_commit(
        conn, files=files, session_id=session_id
    )

    file_preview = ", ".join(files[:MAX_FILES_IN_CONTENT])
    if len(files) > MAX_FILES_IN_CONTENT:
        file_preview += f" (+{len(files) - MAX_FILES_IN_CONTENT} more)"
    content = f"files ({len(files)}): {file_preview}"

    existing_id = _find_commit_node(conn, sha)
    created = existing_id is None
    if existing_id:
        commit_id = existing_id
        now = utc_now_iso()
        conn.execute(
            """
            UPDATE nodes
            SET title = ?, content = ?, git_branch = COALESCE(?, git_branch),
                session_id = COALESCE(?, session_id), updated_at = ?
            WHERE id = ?
            """,
            (subject[:240], content, branch, resolved_session, now, commit_id),
        )
    else:
        record = create_neuron(
            conn,
            title=subject[:240],
            content=content,
            kind=COMMIT_KIND,
            subtype=COMMIT_SUBTYPE,
            source="git_note",
            session_id=resolved_session,
            confidence=1.0,
        )
        commit_id = record.id
        conn.execute(
            """
            UPDATE nodes
            SET git_hash = ?, git_branch = ?, updated_at = ?
            WHERE id = ?
            """,
            (sha, branch, utc_now_iso(), commit_id),
        )

    files_linked = 0
    for path in files:
        code_id = _resolve_code_file_id(conn, path)
        if code_id is None:
            continue
        _insert_edge(
            conn,
            from_id=commit_id,
            to_id=code_id,
            relationship="about_file",
            weight=1.0,
        )
        files_linked += 1

    neurons_linked = 0
    for neuron_id in _neurons_to_link(
        conn, files=files, session_id=resolved_session
    ):
        _insert_edge(
            conn,
            from_id=commit_id,
            to_id=neuron_id,
            relationship="relates_to",
            weight=0.9,
        )
        neurons_linked += 1
        conn.execute(
            """
            UPDATE nodes
            SET git_hash = COALESCE(git_hash, ?),
                git_branch = COALESCE(git_branch, ?)
            WHERE id = ?
            """,
            (sha, branch, neuron_id),
        )

    logger.info(
        "git-note sha=%s created=%s files=%d neurons=%d session=%s",
        sha[:12],
        created,
        files_linked,
        neurons_linked,
        resolved_session,
    )
    return GitNoteResult(
        commit_id=commit_id,
        git_hash=sha,
        created=created,
        files_linked=files_linked,
        neurons_linked=neurons_linked,
        session_id=resolved_session,
        subject=subject,
    )


def detect_external_hook_manager(project_dir: Path) -> str | None:
    """Return a reason string if husky/lefthook/core.hooksPath owns hooks."""
    root = project_dir.resolve()
    hooks_path = _run_git(root, "config", "--get", "core.hooksPath")
    if hooks_path.returncode == 0:
        value = (hooks_path.stdout or "").strip()
        if value:
            return f"core.hooksPath={value}"
    if (root / ".husky").is_dir():
        return ".husky/ present"
    for name in ("lefthook.yml", "lefthook.yaml", ".lefthook.yml"):
        if (root / name).is_file():
            return f"{name} present"
    return None


def _hook_snippet(brainkm_bin: str) -> str:
    """Prefer PATH ``brainkm``; fall back to resolved bin if PATH misses."""
    bin_q = quote(brainkm_bin)
    return (
        f"{HOOK_MARKER}\n"
        f'ROOT="$(git rev-parse --show-toplevel)"\n'
        f'if command -v brainkm >/dev/null 2>&1; then\n'
        f'  brainkm git-note --project-dir "$ROOT" >/dev/null 2>&1 || true\n'
        f"elif [ -x {bin_q} ]; then\n"
        f'  {bin_q} git-note --project-dir "$ROOT" >/dev/null 2>&1 || true\n'
        f"fi\n"
    )


def _strip_brainkm_hook_block(text: str) -> str:
    """Remove brainkm commit-trace block (legacy one-liner or PATH if/fi form)."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    while i < len(lines):
        if HOOK_MARKER not in lines[i]:
            out.append(lines[i])
            i += 1
            continue
        i += 1
        saw_if = False
        while i < len(lines):
            raw = lines[i]
            s = raw.strip()
            if "if command -v brainkm" in raw:
                saw_if = True
            if saw_if and s == "fi":
                i += 1
                if i < len(lines) and lines[i].strip() == "":
                    i += 1
                break
            if not saw_if and s == "":
                i += 1
                break
            i += 1
    return "".join(out)


def install_post_commit_hook(
    project_dir: Path,
    *,
    brainkm_bin: str,
    force: bool = False,
) -> HookInstallResult:
    """Write ``.git/hooks/post-commit`` that runs ``brainkm git-note``.

    Skips when an external hook manager owns hooks (unless ``force``).
    """
    root = project_dir.resolve()
    warnings: list[str] = []

    external = detect_external_hook_manager(root)
    if external and not force:
        msg = (
            f"commit-trace hook skipped ({external}); "
            "wire brainkm git-note into that manager manually, or unset it"
        )
        logger.warning(msg)
        return HookInstallResult(
            path=None,
            installed=False,
            skipped=True,
            warnings=(msg,),
        )

    git_dir = _run_git(root, "rev-parse", "--git-dir")
    if git_dir.returncode != 0:
        msg = f"install post-commit: not a git repo at {root}"
        logger.warning(msg)
        return HookInstallResult(
            path=None,
            installed=False,
            skipped=True,
            warnings=(msg,),
        )

    hooks_dir = Path(git_dir.stdout.strip())
    if not hooks_dir.is_absolute():
        hooks_dir = root / hooks_dir
    hooks_dir = hooks_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / "post-commit"
    snippet = _hook_snippet(brainkm_bin)
    appended = False

    if hook_path.is_file():
        existing = hook_path.read_text(encoding="utf-8")
        had_marker = HOOK_MARKER in existing
        cleaned = _strip_brainkm_hook_block(existing).rstrip()
        if cleaned and not had_marker:
            appended = True
            warnings.append(
                "appended brainkm block to existing post-commit "
                "(foreign hook preserved)"
            )
        new_body = (cleaned + "\n\n" + snippet) if cleaned else ("#!/bin/sh\n" + snippet)
        hook_path.write_text(
            new_body if new_body.endswith("\n") else new_body + "\n",
            encoding="utf-8",
        )
    else:
        hook_path.write_text("#!/bin/sh\n" + snippet, encoding="utf-8")

    hook_path.chmod(hook_path.stat().st_mode | 0o111)
    return HookInstallResult(
        path=hook_path,
        installed=True,
        skipped=False,
        warnings=tuple(warnings),
        appended_to_existing=appended,
    )


def post_commit_hook_installed(project_dir: Path) -> bool:
    """True when ``.git/hooks/post-commit`` contains the brainkm marker."""
    root = project_dir.resolve()
    git_dir = _run_git(root, "rev-parse", "--git-dir")
    if git_dir.returncode != 0:
        return False
    hooks_dir = Path(git_dir.stdout.strip())
    if not hooks_dir.is_absolute():
        hooks_dir = root / hooks_dir
    hook_path = hooks_dir / "hooks" / "post-commit"
    if not hook_path.is_file():
        return False
    try:
        return HOOK_MARKER in hook_path.read_text(encoding="utf-8")
    except OSError:
        return False


def uninstall_post_commit_hook(project_dir: Path) -> bool:
    """Remove brainkm block from post-commit; delete file if only ours remained."""
    root = project_dir.resolve()
    git_dir = _run_git(root, "rev-parse", "--git-dir")
    if git_dir.returncode != 0:
        return False
    hooks_dir = Path(git_dir.stdout.strip())
    if not hooks_dir.is_absolute():
        hooks_dir = root / hooks_dir
    hook_path = hooks_dir / "hooks" / "post-commit"
    if not hook_path.is_file():
        return False
    text = hook_path.read_text(encoding="utf-8")
    if HOOK_MARKER not in text:
        return False
    cleaned = _strip_brainkm_hook_block(text).strip()
    if cleaned in {"", "#!/bin/sh", "#!/bin/bash"}:
        hook_path.unlink(missing_ok=True)
    else:
        hook_path.write_text(cleaned + "\n", encoding="utf-8")
    return True
