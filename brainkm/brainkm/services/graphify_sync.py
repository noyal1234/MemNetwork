"""Graphify extract orchestration, sync, and background scheduler."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from brainkm.adapters.graphify import load_graph_json, resolve_graph_json_path
from brainkm.db.connection import connect
from brainkm.db.paths import brain_db_path, brain_dir
from brainkm.logging_config import get_logger
from brainkm.models.brain_config import BrainConfig, GraphifyConfig
from brainkm.models.graphify import (
    GraphifyExtractResult,
    GraphifyProbeResult,
    GraphSyncResult,
)
from brainkm.services.channel_health import graph_available, latest_graph_import_status
from brainkm.services.config_loader import load_brain_config
from brainkm.services.graph_import import import_project_graph

logger = get_logger("services.graphify_sync")

REQUEST_FILENAME = "graph_sync.requested"
LOCK_FILENAME = "graph_sync.lock"
STALE_LOCK_SECONDS = 30 * 60  # 30 minutes
POLL_INTERVAL_SECONDS = 5.0
STOP_JOIN_TIMEOUT_SECONDS = 330.0


def resolve_graphify_binary(config: GraphifyConfig) -> Path | None:
    """Resolve graphify CLI: absolute path, same venv as brainkm, then PATH."""
    candidate = Path(config.extract_binary)
    if candidate.is_absolute() and candidate.is_file():
        return candidate

    venv_binary = Path(sys.executable).resolve().parent / config.extract_binary
    if venv_binary.is_file():
        return venv_binary

    which_path = shutil.which(config.extract_binary)
    if which_path:
        return Path(which_path)
    return None


def probe_graphify(config: GraphifyConfig | None = None) -> GraphifyProbeResult:
    cfg = config or GraphifyConfig()
    resolved = resolve_graphify_binary(cfg)
    if resolved is not None:
        return GraphifyProbeResult(found=True, binary_path=str(resolved))
    return GraphifyProbeResult(
        found=False,
        binary_path=None,
        reason=(
            f"graphify binary '{cfg.extract_binary}' not found — "
            "install with: pip install graphifyy  or  pip install -e './brainkm[graphify]'"
        ),
    )


def resolve_extract_targets(project_dir: Path, config: BrainConfig) -> list[str]:
    if config.graphify.extract_scope == "project":
        return ["."]
    return list(config.project_roots)


def _graph_json_path(project_dir: Path, config: BrainConfig) -> Path:
    return resolve_graph_json_path(project_dir, graph_json=config.graphify.graph_json)


def _request_flag_path(project_dir: Path) -> Path:
    return brain_dir(project_dir) / REQUEST_FILENAME


def _lock_path(project_dir: Path) -> Path:
    return brain_dir(project_dir) / LOCK_FILENAME


def request_graph_sync(project_dir: Path | None = None) -> None:
    """Touch a request flag for the MCP background scheduler (fast, hook-safe)."""
    root = (project_dir if project_dir is not None else Path.cwd()).resolve()
    flag = _request_flag_path(root)
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")


def clear_graph_sync_request(project_dir: Path) -> None:
    flag = _request_flag_path(project_dir)
    if flag.is_file():
        flag.unlink()


def _clear_stale_lock(lock_path: Path, *, max_age_seconds: float = STALE_LOCK_SECONDS) -> bool:
    """Remove a lock file left behind after a crash; return True if cleared."""
    if not lock_path.is_file():
        return False
    try:
        age = time.time() - lock_path.stat().st_mtime
    except OSError:
        return False
    if age < max_age_seconds:
        return False
    try:
        lock_path.unlink()
        logger.warning("removed stale graph_sync.lock age_seconds=%.0f", age)
        return True
    except OSError:
        return False


def _try_acquire_lock(lock_path: Path) -> bool:
    _clear_stale_lock(lock_path)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        return True
    except FileExistsError:
        return False


def _release_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


def _validate_graph_json(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return False
    return True


def run_graphify_extract(
    project_dir: Path,
    config: BrainConfig,
    *,
    force: bool = False,
) -> GraphifyExtractResult:
    """Run upstream graphify extract; verify graph.json exists and parses."""
    graph_path = _graph_json_path(project_dir, config)
    probe = probe_graphify(config.graphify)
    if not probe.found:
        return GraphifyExtractResult(
            ok=False,
            graph_path=str(graph_path),
            stderr_snippet=probe.reason,
        )

    binary = Path(probe.binary_path)  # type: ignore[arg-type]
    targets = resolve_extract_targets(project_dir, config)
    # code_only: graphify update is AST-only (no LLM). extract scans docs and requires API keys.
    subcommand = "update" if config.graphify.code_only else "extract"
    cmd: list[str] = [str(binary), subcommand, *targets, *config.graphify.extract_extra_args]
    if force:
        cmd.append("--force")
    if config.graphify.code_only and "--no-cluster" not in config.graphify.extract_extra_args:
        cmd.append("--no-cluster")

    logger.info("graphify %s starting cmd=%s cwd=%s", subcommand, " ".join(cmd), project_dir)
    try:
        completed = subprocess.run(
            cmd,
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=config.graphify.extract_timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("graphify extract failed: %s", exc)
        return GraphifyExtractResult(
            ok=False,
            graph_path=str(graph_path),
            stderr_snippet=str(exc),
        )

    stderr_snippet = (completed.stderr or completed.stdout or "")[:500].strip() or None
    if completed.returncode != 0:
        logger.warning(
            "graphify extract exit=%d stderr=%s",
            completed.returncode,
            stderr_snippet,
        )
        return GraphifyExtractResult(
            ok=False,
            graph_path=str(graph_path),
            exit_code=completed.returncode,
            stderr_snippet=stderr_snippet,
        )

    if not _validate_graph_json(graph_path):
        return GraphifyExtractResult(
            ok=False,
            graph_path=str(graph_path),
            exit_code=completed.returncode,
            stderr_snippet="graph.json missing or invalid after extract",
        )

    return GraphifyExtractResult(
        ok=True,
        graph_path=str(graph_path),
        exit_code=completed.returncode,
    )


def last_completed_import_at(project_dir: Path) -> datetime | None:
    db = brain_db_path(project_dir)
    if not db.is_file():
        return None
    conn = connect(db)
    try:
        row = conn.execute(
            """
            SELECT completed_at FROM graph_import_runs
            WHERE status = 'completed'
            ORDER BY completed_at DESC
            LIMIT 1
            """
        ).fetchone()
        if not row or row[0] is None:
            return None
        return datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
    finally:
        conn.close()


def graph_json_newer_than_import(project_dir: Path, config: BrainConfig) -> bool:
    graph_path = _graph_json_path(project_dir, config)
    if not graph_path.is_file():
        return False
    last_import = last_completed_import_at(project_dir)
    if last_import is None:
        return True
    graph_mtime = datetime.fromtimestamp(graph_path.stat().st_mtime, tz=UTC)
    return graph_mtime > last_import.astimezone(UTC)


def seconds_since_last_successful_sync(project_dir: Path) -> float | None:
    last = last_completed_import_at(project_dir)
    if last is None:
        return None
    return (datetime.now(UTC) - last.astimezone(UTC)).total_seconds()


def sync_graph(
    project_dir: Path | None = None,
    config: BrainConfig | None = None,
    *,
    extract: bool = True,
    force: bool = False,
) -> GraphSyncResult:
    """Extract (optional) and import graph.json with fail-safe guards."""
    root = (project_dir if project_dir is not None else Path.cwd()).resolve()
    cfg = config or load_brain_config(root)

    if not cfg.graphify.enabled:
        return GraphSyncResult(
            status="skipped",
            graph_available=False,
            message="graphify disabled in config",
        )

    lock_path = _lock_path(root)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if not _try_acquire_lock(lock_path):
        available = _graph_available_for_project(root)
        return GraphSyncResult(
            status="skipped_locked",
            graph_available=available,
            message="graph sync already in progress",
        )

    extract_ok: bool | None = None
    try:
        if extract:
            extract_result = run_graphify_extract(root, cfg, force=force)
            extract_ok = extract_result.ok
            if not extract_result.ok:
                available = _graph_available_for_project(root)
                return GraphSyncResult(
                    status="extract_failed",
                    graph_available=available,
                    extract_ok=False,
                    message=extract_result.stderr_snippet,
                )

        graph_path = _graph_json_path(root, cfg)
        if not graph_path.is_file():
            available = _graph_available_for_project(root)
            return GraphSyncResult(
                status="missing_graph",
                graph_available=available,
                extract_ok=extract_ok,
                message=f"graph.json not found: {graph_path}",
            )

        parsed = load_graph_json(graph_path, code_only=True)
        if len(parsed.nodes) == 0:
            available = _graph_available_for_project(root)
            return GraphSyncResult(
                status="skipped_empty",
                graph_available=available,
                extract_ok=extract_ok,
                message="0 code nodes after code_only filter; prior graph preserved",
            )

        import_result = import_project_graph(
            project_dir=root,
            config=cfg,
            graph_path=graph_path,
        )
        available = _graph_available_for_project(root)
        if import_result.status == "skipped_empty":
            return GraphSyncResult(
                status="skipped_empty",
                graph_available=available,
                extract_ok=extract_ok,
                import_result=import_result,
                message="import refused empty graph; prior code nodes preserved",
            )

        clear_graph_sync_request(root)
        return GraphSyncResult(
            status=import_result.status,
            graph_available=available,
            extract_ok=extract_ok,
            import_result=import_result,
        )
    finally:
        _release_lock(lock_path)


def _graph_available_for_project(project_dir: Path) -> bool:
    db = brain_db_path(project_dir)
    if not db.is_file():
        return False
    conn = connect(db)
    try:
        return graph_available(conn)
    finally:
        conn.close()


def build_graph_status(
    project_dir: Path | None = None,
    config: BrainConfig | None = None,
) -> dict[str, object]:
    """Structured status for CLI and diagnostics."""
    root = (project_dir if project_dir is not None else Path.cwd()).resolve()
    cfg = config or load_brain_config(root)
    probe = probe_graphify(cfg.graphify)
    graph_path = _graph_json_path(root, cfg)

    code_node_count = 0
    import_status: str | None = None
    last_import_at: str | None = None
    available = False
    db = brain_db_path(root)
    if db.is_file():
        conn = connect(db)
        try:
            available = graph_available(conn)
            import_status = latest_graph_import_status(conn)
            row = conn.execute(
                """
                SELECT completed_at, node_count FROM graph_import_runs
                WHERE status = 'completed'
                ORDER BY completed_at DESC LIMIT 1
                """
            ).fetchone()
            if row:
                last_import_at = str(row[0]) if row[0] else None
                code_node_count = int(row[1] or 0)
            else:
                code_node_count = int(
                    conn.execute("SELECT COUNT(*) FROM nodes WHERE kind = 'code'").fetchone()[0]
                )
        finally:
            conn.close()

    graph_mtime: str | None = None
    stale = False
    if graph_path.is_file():
        graph_mtime = datetime.fromtimestamp(
            graph_path.stat().st_mtime, tz=UTC
        ).isoformat()
        last = last_completed_import_at(root)
        if last is not None:
            stale = graph_path.stat().st_mtime > last.timestamp()
        else:
            stale = True

    pending_request = _request_flag_path(root).is_file()

    return {
        "graphify_binary": probe.binary_path,
        "graphify_found": probe.found,
        "graphify_reason": probe.reason,
        "graph_json": str(graph_path),
        "graph_json_exists": graph_path.is_file(),
        "graph_json_mtime": graph_mtime,
        "graph_stale": stale,
        "graph_available": available,
        "last_import_status": import_status,
        "last_import_at": last_import_at,
        "code_node_count": code_node_count,
        "auto_sync_enabled": cfg.graphify.auto_sync.enabled,
        "watch_filesystem_enabled": cfg.graphify.auto_sync.watch_filesystem,
        "sync_request_pending": pending_request,
    }


class GraphSyncScheduler:
    """Debounced background graph sync for the long-lived MCP server process."""

    def __init__(self, project_dir: Path, config: BrainConfig) -> None:
        self.project_dir = project_dir.resolve()
        self.config = config
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._debounce_timer: threading.Timer | None = None
        self._debounce_lock = threading.Lock()
        self._sync_in_progress = threading.Event()
        self._fs_watch: object | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="graph-sync-scheduler",
            daemon=True,
        )
        self._thread.start()
        self._maybe_start_filesystem_watch()
        self._maybe_schedule_startup_sync()
        logger.info("GraphSyncScheduler started project_dir=%s", self.project_dir)

    def stop(self, *, timeout: float = STOP_JOIN_TIMEOUT_SECONDS) -> None:
        self._stop.set()
        self._stop_filesystem_watch()
        with self._debounce_lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
                self._debounce_timer = None
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        logger.info("GraphSyncScheduler stopped project_dir=%s", self.project_dir)

    def _maybe_start_filesystem_watch(self) -> None:
        auto = self.config.graphify.auto_sync
        if (
            not self.config.graphify.enabled
            or not auto.enabled
            or not auto.watch_filesystem
        ):
            return
        from brainkm.services.graphify_watch import GraphifyFilesystemWatch

        watch = GraphifyFilesystemWatch(self.project_dir, config=self.config)
        watch.start()
        self._fs_watch = watch

    def _stop_filesystem_watch(self) -> None:
        watch = self._fs_watch
        self._fs_watch = None
        if watch is None:
            return
        stop = getattr(watch, "stop", None)
        if callable(stop):
            stop(timeout=5.0)

    def _maybe_schedule_startup_sync(self) -> None:
        flag = _request_flag_path(self.project_dir)
        needs_sync = flag.is_file()
        if not needs_sync and brain_db_path(self.project_dir).is_file():
            conn = connect(brain_db_path(self.project_dir))
            try:
                elapsed = seconds_since_last_successful_sync(self.project_dir)
                needs_sync = (
                    not graph_available(conn)
                    or (elapsed is not None and elapsed > 24 * 3600)
                    or graph_json_newer_than_import(self.project_dir, self.config)
                )
            finally:
                conn.close()
        if needs_sync:
            self._schedule_sync(reason="startup")

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            if _request_flag_path(self.project_dir).is_file():
                self._schedule_sync(reason="request_flag")
            if self._stop.wait(POLL_INTERVAL_SECONDS):
                break

    def _schedule_sync(self, *, reason: str) -> None:
        if not self.config.graphify.enabled or not self.config.graphify.auto_sync.enabled:
            return

        debounce = self.config.graphify.auto_sync.debounce_seconds

        def fire() -> None:
            if self._stop.is_set():
                return
            self._run_sync_if_allowed(reason=reason)

        with self._debounce_lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
            self._debounce_timer = threading.Timer(debounce, fire)
            self._debounce_timer.daemon = True
            self._debounce_timer.start()

    def _run_sync_if_allowed(self, *, reason: str) -> None:
        if self._sync_in_progress.is_set():
            return

        min_interval = self.config.graphify.auto_sync.min_interval_seconds
        elapsed = seconds_since_last_successful_sync(self.project_dir)
        if elapsed is not None and elapsed < min_interval:
            logger.debug(
                "graph sync skipped min_interval reason=%s elapsed=%.1fs",
                reason,
                elapsed,
            )
            return

        self._sync_in_progress.set()
        try:
            result = sync_graph(self.project_dir, self.config, extract=True)
            logger.info(
                "background graph sync reason=%s status=%s graph_available=%s",
                reason,
                result.status,
                result.graph_available,
            )
        except Exception as exc:
            logger.warning("background graph sync failed reason=%s: %s", reason, exc)
        finally:
            self._sync_in_progress.clear()


_scheduler: GraphSyncScheduler | None = None
_scheduler_lock = threading.Lock()


def start_graph_sync_scheduler(project_dir: Path, config: BrainConfig) -> GraphSyncScheduler | None:
    global _scheduler
    if not config.graphify.enabled or not config.graphify.auto_sync.enabled:
        return None
    with _scheduler_lock:
        if _scheduler is not None:
            _scheduler.stop(timeout=5.0)
        _scheduler = GraphSyncScheduler(project_dir, config)
        _scheduler.start()
        return _scheduler


def stop_graph_sync_scheduler(*, timeout: float = STOP_JOIN_TIMEOUT_SECONDS) -> None:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is not None:
            _scheduler.stop(timeout=timeout)
            _scheduler = None


def maybe_import_stale_graph_on_session_end(
    project_dir: Path | None = None,
    config: BrainConfig | None = None,
) -> str | None:
    """SessionEnd fallback: import-only when graph.json is newer than last import."""
    root = (project_dir if project_dir is not None else Path.cwd()).resolve()
    cfg = config or load_brain_config(root)
    if not cfg.graphify.enabled:
        return None

    flag = _request_flag_path(root)
    needs_import = flag.is_file() or graph_json_newer_than_import(root, cfg)
    if not needs_import:
        return None

    try:
        result = sync_graph(root, cfg, extract=False)
        if result.status in {"completed", "skipped_empty", "skipped_locked"}:
            return None
        return result.message or f"graph import fallback: {result.status}"
    except Exception as exc:
        return f"graph import fallback failed: {exc}"
