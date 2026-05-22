"""Shared lifecycle primitive for OmniKB background workers.

Why a base class
----------------
Without this, every new background task (the wiki worker, the
scheduled research dispatcher, future indexers, etc.) would copy the
same ~30 lines of boilerplate: spawn a task, hold a stop event, drain
on shutdown, isolate exceptions, count processed/failed for stats.
Copying it once per worker is fine; copying it three times is a
maintenance liability and a place for subtle bugs (forgotten
``stopping.clear()``, swallowed CancelledError, missed drain timeout).

Subclassing contract
--------------------
Tick-driven workers (the common case) override
:meth:`_loop_iteration` and inherit the rest. Queue-driven workers
that need full control over their wait / dispatch logic override
:meth:`_run` instead and use :meth:`_should_stop` to notice shutdown
requests.

Either style benefits from the shared :meth:`stats`, error counting,
graceful shutdown, and consistent logger naming.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import ClassVar

logger = logging.getLogger(__name__)


class BackgroundWorker:
    """Base for any single-task long-running async worker.

    Subclasses MUST set :attr:`name` so logs are searchable. They MAY
    override :meth:`_loop_iteration` (tick-driven), :meth:`_run`
    (full custody), and :meth:`_drain` (for queue-based drain).
    """

    name: ClassVar[str] = "background-worker"
    DRAIN_TIMEOUT_S: ClassVar[float] = 30.0
    TICK_INTERVAL_S: ClassVar[float] = 1.0

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._processed = 0
        self._failed = 0
        self._logger = logging.getLogger(f"workers.{self.name}")

    # ── lifecycle ──────────────────────────────────────────────

    async def start(self) -> None:
        """Spawn the background task. Idempotent — repeated calls are no-ops."""
        if self._task is not None and not self._task.done():
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name=self.name)
        self._logger.info("started")

    async def stop(self) -> None:
        """Signal stop, drain in-flight work (subclass-defined), then cancel."""
        if self._task is None:
            return
        self._stopping.set()
        # Subclasses with a queue override _drain to call queue.join().
        try:
            await asyncio.wait_for(self._drain(), timeout=self.DRAIN_TIMEOUT_S)
        except asyncio.TimeoutError:
            self._logger.warning("drain timeout — forcing cancel")
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        self._logger.info(
            "stopped (processed=%d failed=%d)",
            self._processed, self._failed,
        )

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def stats(self) -> dict[str, int]:
        return {"processed": self._processed, "failed": self._failed}

    # ── default loops ──────────────────────────────────────────

    async def _run(self) -> None:
        """Default tick-driven loop.

        Calls :meth:`_loop_iteration` once per ``TICK_INTERVAL_S``,
        with per-iteration exception isolation. The sleep is awaited
        on the stop event with a timeout so :meth:`stop` is responsive
        without polling.

        Override this entirely if you need full control (e.g. queue
        consumers waiting on ``queue.get()``).
        """
        self._logger.debug("tick-driven loop entered (interval=%.1fs)", self.TICK_INTERVAL_S)
        while not self._stopping.is_set():
            try:
                await self._loop_iteration()
                self._processed += 1
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001 — never let one tick kill the worker
                self._failed += 1
                self._logger.exception("iteration raised: %s", exc)

            # Sleep until the next tick OR an early stop signal —
            # whichever comes first.
            try:
                await asyncio.wait_for(
                    self._stopping.wait(),
                    timeout=self.TICK_INTERVAL_S,
                )
                # Stopping event fired — exit cleanly.
                return
            except asyncio.TimeoutError:
                continue

    async def _loop_iteration(self) -> None:
        """One tick of work. Default: do nothing.

        Tick-driven subclasses override this. Queue-driven subclasses
        that override :meth:`_run` directly never call this.
        """
        return

    async def _drain(self) -> None:
        """Wait for in-flight work to settle before shutdown.

        Default: nothing to drain. Queue-based subclasses override
        this to await ``queue.join()``.
        """
        return

    # ── helpers for subclasses overriding _run ────────────────

    def _should_stop(self) -> bool:
        return self._stopping.is_set()

    async def _isolate(self, coro) -> bool:
        """Run a coroutine with the same exception isolation the default
        loop uses. Returns True on success, False on swallowed failure.
        Useful for queue-driven subclasses that want to share the
        accounting (processed / failed counters)."""
        try:
            await coro
            self._processed += 1
            return True
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._failed += 1
            self._logger.exception("isolated coro raised: %s", exc)
            return False
