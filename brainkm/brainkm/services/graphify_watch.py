"""Opt-in filesystem watch for Graphify auto-sync (multi-IDE edits).

Delegates to ``request_graph_sync`` so debounce / min-interval stay in
``GraphSyncScheduler``. Does not replace PostToolUse — complements it.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

from brainkm.logging_config import get_logger
from brainkm.models.brain_config import BrainConfig
from brainkm.services.config_loader import load_brain_config

logger = get_logger("services.graphify_watch")

# Directory name segments ignored at any depth (feedback-loop + noise).
ALWAYS_IGNORE_SEGMENTS = frozenset(
    {
        ".git",
        ".brain",
        "graphify-out",
        ".venv",
        "venv",
        "node_modules",
        ".pytest_cache",
        "__pycache__",
        ".egg-info",
        ".cursor",
        "dist",
        "build",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
    }
)

# Source extensions aligned with adapters/graphify._FILE_LABEL (positive filter).
SOURCE_EXTENSIONS = frozenset(
    {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".go",
        ".rs",
        ".java",
        ".rb",
        ".sql",
        ".sh",
        ".cpp",
        ".c",
        ".h",
        ".cs",
        ".vue",
        ".svelte",
    }
)

GRAPHIFYIGNORE_NAME = ".graphifyignore"


def load_graphifyignore_patterns(project_dir: Path) -> list[str]:
    """Load simple ignore patterns from ``.graphifyignore`` (if present)."""
    path = project_dir / GRAPHIFYIGNORE_NAME
    if not path.is_file():
        return []
    patterns: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        patterns.append(stripped)
    return patterns


def _path_has_ignored_segment(rel: Path) -> bool:
    for part in rel.parts:
        if part in ALWAYS_IGNORE_SEGMENTS:
            return True
        if part.endswith(".egg-info"):
            return True
    return False


def _matches_graphifyignore(rel_posix: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        # Directory-style prefix: "docs/" or "docs"
        if pattern.endswith("/"):
            prefix = pattern.rstrip("/")
            if rel_posix == prefix or rel_posix.startswith(prefix + "/"):
                return True
            continue
        if "/" not in pattern and "*" not in pattern and "?" not in pattern:
            # Bare directory name treated as prefix
            if rel_posix == pattern or rel_posix.startswith(pattern + "/"):
                return True
            continue
        if fnmatch.fnmatch(rel_posix, pattern):
            return True
        # Also match basename-only globs like "*.md"
        if "/" not in pattern and fnmatch.fnmatch(Path(rel_posix).name, pattern):
            return True
    return False


def should_request_sync(
    path: Path,
    project_dir: Path,
    *,
    ignore_patterns: list[str] | None = None,
) -> bool:
    """Return True if a filesystem event for ``path`` should request a graph sync."""
    root = project_dir.resolve()
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path

    try:
        rel = resolved.relative_to(root)
    except ValueError:
        # Outside project — ignore
        return False

    if _path_has_ignored_segment(rel):
        return False

    patterns = ignore_patterns
    if patterns is None:
        patterns = load_graphifyignore_patterns(root)
    if patterns and _matches_graphifyignore(rel.as_posix(), patterns):
        return False

    suffix = resolved.suffix.lower()
    if suffix not in SOURCE_EXTENSIONS:
        return False

    return True


def resolve_watch_roots(project_dir: Path, config: BrainConfig) -> list[Path]:
    """Absolute existing paths under the project that should be observed."""
    from brainkm.services.graphify_sync import resolve_extract_targets

    root = project_dir.resolve()
    targets = resolve_extract_targets(root, config)
    roots: list[Path] = []
    for target in targets:
        candidate = (root / target).resolve() if not Path(target).is_absolute() else Path(target)
        if candidate.exists():
            roots.append(candidate)
    return roots


class GraphifyFilesystemWatch:
    """Watch project roots and request background graph sync on source edits."""

    def __init__(
        self,
        project_dir: Path,
        *,
        config: BrainConfig | None = None,
    ) -> None:
        self.project_dir = project_dir.resolve()
        self.config = config or load_brain_config(self.project_dir)
        self._observer: object | None = None
        self._ignore_patterns = load_graphifyignore_patterns(self.project_dir)

    @property
    def is_active(self) -> bool:
        observer = self._observer
        if observer is None:
            return False
        return bool(getattr(observer, "is_alive", lambda: False)())

    def start(self) -> None:
        if self._observer is not None:
            return
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            logger.warning(
                "watchdog not installed — filesystem watch disabled "
                "(pip install watchdog or reinstall brainkm)"
            )
            return

        roots = resolve_watch_roots(self.project_dir, self.config)
        if not roots:
            logger.warning(
                "graphify filesystem watch: no watch roots under %s",
                self.project_dir,
            )
            return

        watch = self

        class Handler(FileSystemEventHandler):
            def on_modified(self, event):  # noqa: N802
                if not event.is_directory:
                    watch._maybe_request(Path(event.src_path))

            def on_created(self, event):  # noqa: N802
                if not event.is_directory:
                    watch._maybe_request(Path(event.src_path))

            def on_moved(self, event):  # noqa: N802
                if not event.is_directory:
                    dest = getattr(event, "dest_path", None)
                    if dest:
                        watch._maybe_request(Path(dest))

        observer = Observer()
        handler = Handler()
        for path in roots:
            observer.schedule(handler, str(path), recursive=True)
        observer.daemon = True
        observer.start()
        self._observer = observer
        logger.info(
            "graphify filesystem watch started roots=%d project_dir=%s",
            len(roots),
            self.project_dir,
        )

    def stop(self, *, timeout: float = 5.0) -> None:
        observer = self._observer
        self._observer = None
        if observer is None:
            return
        try:
            observer.stop()  # type: ignore[attr-defined]
            observer.join(timeout)  # type: ignore[attr-defined]
        except Exception as exc:
            logger.warning("graphify filesystem watch stop failed: %s", exc)
        logger.info("graphify filesystem watch stopped project_dir=%s", self.project_dir)

    def _maybe_request(self, path: Path) -> None:
        if not should_request_sync(
            path,
            self.project_dir,
            ignore_patterns=self._ignore_patterns,
        ):
            return
        logger.debug("graphify watch requesting sync path=%s", path)
        from brainkm.services.graphify_sync import request_graph_sync

        request_graph_sync(self.project_dir)
