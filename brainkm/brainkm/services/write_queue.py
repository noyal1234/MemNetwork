"""Single-writer asyncio queue for SQLite mutations with busy retry."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from collections.abc import Callable
from typing import Any, TypeVar

from brainkm.logging_config import get_logger

logger = get_logger("services.write_queue")

T = TypeVar("T")

_MAX_RETRIES = 5
_BASE_DELAY_SECONDS = 0.05


class WriteQueue:
    """Serialize blocking SQLite writes on a background worker thread."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[
            tuple[Callable[..., T], tuple[Any, ...], dict[str, Any], asyncio.Future[T]] | None
        ] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None

    def _has_live_worker(self) -> bool:
        """True when the worker is still running on the *current* event loop.

        Async tests (and MCP) start the global queue on a loop that then closes.
        A leftover ``_worker_task`` that is done or bound to another loop must
        not be treated as a live MCP worker — otherwise ``run_blocking`` enqueues
        work nobody will process and hangs forever.
        """
        task = self._worker_task
        if task is None or task.done():
            return False
        try:
            return task.get_loop() is asyncio.get_running_loop()
        except RuntimeError:
            return False

    def _discard_stale_worker(self) -> None:
        """Drop a dead/cross-loop worker and its queue without awaiting it."""
        self._worker_task = None
        self._queue = asyncio.Queue()

    async def start(self) -> None:
        if self._has_live_worker():
            return
        if self._worker_task is not None:
            self._discard_stale_worker()
        self._worker_task = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        if self._worker_task is None:
            return
        if self._worker_task.done():
            self._worker_task = None
            return
        if not self._has_live_worker():
            # Task is still marked incomplete but belongs to another loop —
            # we cannot safely await it from here.
            self._discard_stale_worker()
            return
        await self._queue.put(None)
        await self._worker_task
        self._worker_task = None

    async def run(self, fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
        """Enqueue a blocking callable and await its result."""
        await self.start()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[T] = loop.create_future()
        await self._queue.put((fn, args, kwargs, future))
        return await future

    async def _worker(self) -> None:
        while True:
            item = await self._queue.get()
            if item is None:
                break

            fn, args, kwargs, future = item
            try:
                result = await asyncio.to_thread(self._run_with_retry, fn, *args, **kwargs)
            except Exception as exc:
                if not future.done():
                    future.set_exception(exc)
            else:
                if not future.done():
                    future.set_result(result)

    def _run_with_retry(self, fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
        for attempt in range(_MAX_RETRIES):
            try:
                return fn(*args, **kwargs)
            except sqlite3.OperationalError as exc:
                message = str(exc).lower()
                if "locked" in message and attempt < _MAX_RETRIES - 1:
                    delay = _BASE_DELAY_SECONDS * (2**attempt)
                    logger.debug("SQLITE_BUSY retry %d in %.3fs", attempt + 1, delay)
                    time.sleep(delay)
                    continue
                raise
        raise RuntimeError("unreachable")


_write_queue: WriteQueue | None = None


def get_write_queue() -> WriteQueue:
    global _write_queue
    if _write_queue is None:
        _write_queue = WriteQueue()
    return _write_queue


def reset_write_queue_for_tests() -> None:
    """Drop the process-global queue (test isolation only)."""
    global _write_queue
    _write_queue = None


def run_blocking(fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Run ``fn`` through the WriteQueue from sync CLI code.

    Starts the queue worker if MCP is not already running; stops it again when
    this call started the worker (does not stop a live MCP server queue).
    """
    import anyio

    async def _run() -> T:
        queue = get_write_queue()
        started_here = not queue._has_live_worker()
        if started_here:
            await queue.start()
        try:
            return await queue.run(fn, *args, **kwargs)
        finally:
            if started_here:
                await queue.stop()

    return anyio.run(_run)
