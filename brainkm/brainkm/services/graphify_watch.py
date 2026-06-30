"""Graphify filesystem watch — delegates to graphify_sync (optional CLI use)."""

from __future__ import annotations

import threading
from pathlib import Path

from brainkm.logging_config import get_logger
from brainkm.models.brain_config import BrainConfig
from brainkm.services.config_loader import load_brain_config
from brainkm.services.graphify_sync import request_graph_sync, resolve_graphify_binary

logger = get_logger("services.graphify_watch")

DEBOUNCE_SECONDS = 5.0


class GraphifyDebouncer:
    """Coalesce filesystem events before requesting a background graph sync."""

    def __init__(
        self,
        project_dir: Path,
        *,
        config: BrainConfig | None = None,
        debounce_seconds: float = DEBOUNCE_SECONDS,
    ) -> None:
        self.project_dir = project_dir.resolve()
        self.config = config or load_brain_config(self.project_dir)
        self.debounce_seconds = debounce_seconds
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def notify_change(self, path: Path | None = None) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce_seconds, self._request_sync)
            self._timer.daemon = True
            self._timer.start()
        if path is not None:
            logger.debug("graphify watch debounce scheduled path=%s", path)

    def _request_sync(self) -> None:
        logger.info("graphify watch requesting background sync project_dir=%s", self.project_dir)
        request_graph_sync(self.project_dir)

    def start_watchdog(self, watch_paths: list[Path] | None = None) -> None:
        """Start a filesystem observer (optional — requires watchdog)."""
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            logger.warning("watchdog not available — graphify watch manual only")
            return

        binary = resolve_graphify_binary(self.config.graphify)
        if binary is None:
            logger.warning("graphify binary not found — watch will only set sync flags")

        paths = watch_paths or [self.project_dir]
        debouncer = self

        class Handler(FileSystemEventHandler):
            def on_modified(self, event):  # noqa: N802
                if not event.is_directory:
                    debouncer.notify_change(Path(event.src_path))

            def on_created(self, event):  # noqa: N802
                if not event.is_directory:
                    debouncer.notify_change(Path(event.src_path))

        observer = Observer()
        for path in paths:
            if path.exists():
                observer.schedule(Handler(), str(path), recursive=True)
        observer.start()
        logger.info("graphify watchdog started paths=%d", len(paths))
