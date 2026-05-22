"""Tests for the BackgroundWorker base class.

The base wraps a single asyncio.Task with start/stop/error-isolation/
stats. We assert two flavours:

1. **Tick-driven** subclass: inherits the default `_run` and only
   overrides `_loop_iteration`. The base must call it on schedule,
   isolate exceptions, and stop within one tick when stop() is called.

2. **Queue-driven** subclass: overrides `_run` directly (mirrors
   WikiWorker). The base must still provide working start/stop/
   stats/_should_stop machinery.

We deliberately use very short tick intervals so the test suite stays
fast.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.workers import BackgroundWorker


# ─── Tick-driven subclass ─────────────────────────────────────────


class _CountingTickWorker(BackgroundWorker):
    """Tick-driven worker that just increments a counter each tick."""
    name = "counting-tick"
    TICK_INTERVAL_S = 0.05  # 50ms — fast enough for tests, slow enough to be observable

    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    async def _loop_iteration(self) -> None:
        self.count += 1


class _FlakyTickWorker(BackgroundWorker):
    """Every 3rd tick raises to verify exception isolation."""
    name = "flaky-tick"
    TICK_INTERVAL_S = 0.02

    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    async def _loop_iteration(self) -> None:
        self.count += 1
        if self.count % 3 == 0:
            raise RuntimeError(f"synthetic failure on tick {self.count}")


# ─── Queue-driven subclass ─────────────────────────────────────────


class _SimpleQueueWorker(BackgroundWorker):
    """Queue-driven worker that mirrors WikiWorker's pattern."""
    name = "queue-worker"
    DRAIN_TIMEOUT_S = 1.0

    def __init__(self) -> None:
        super().__init__()
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self.handled: list[str] = []

    async def enqueue(self, item: str) -> None:
        await self._queue.put(item)

    async def _drain(self) -> None:
        await self._queue.join()

    async def _run(self) -> None:
        while True:
            try:
                try:
                    item = await asyncio.wait_for(self._queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    if self._should_stop() and self._queue.empty():
                        return
                    continue
            except asyncio.CancelledError:
                return
            try:
                self.handled.append(item)
                self._processed += 1
            finally:
                self._queue.task_done()


# ─── Tick-driven tests ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tick_worker_runs_iterations():
    """A tick-driven worker increments the counter on each tick."""
    w = _CountingTickWorker()
    await w.start()
    # Sleep long enough for ~5 ticks (5 * 50ms = 250ms; sleep 220ms).
    await asyncio.sleep(0.22)
    await w.stop()

    # Count should be at least 3 (allow scheduler jitter).
    assert w.count >= 3
    assert not w.is_running
    assert w.stats()["processed"] == w.count
    assert w.stats()["failed"] == 0


@pytest.mark.asyncio
async def test_tick_worker_isolates_exceptions():
    """A failing iteration must not abort the loop."""
    w = _FlakyTickWorker()
    await w.start()
    await asyncio.sleep(0.15)
    await w.stop()

    # Some iterations succeeded, some failed.
    assert w.count >= 4
    stats = w.stats()
    assert stats["failed"] >= 1, "at least one synthetic failure should have been counted"
    assert stats["processed"] >= 1


@pytest.mark.asyncio
async def test_tick_worker_start_is_idempotent():
    """Calling start() twice doesn't spawn a second task."""
    w = _CountingTickWorker()
    await w.start()
    first_task = w._task
    await w.start()  # no-op
    assert w._task is first_task
    await w.stop()


@pytest.mark.asyncio
async def test_tick_worker_stop_before_start_is_safe():
    """stop() on a never-started worker should not raise."""
    w = _CountingTickWorker()
    await w.stop()  # nothing to do — but must not crash
    assert not w.is_running


# ─── Queue-driven tests ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_queue_worker_processes_items_in_order():
    """A queue-driven worker drains its queue and exposes proper stats."""
    w = _SimpleQueueWorker()
    await w.start()
    for i in range(5):
        await w.enqueue(f"item-{i}")
    # Wait for the queue to drain.
    await asyncio.sleep(0.3)
    await w.stop()

    assert w.handled == [f"item-{i}" for i in range(5)]
    assert w.stats()["processed"] == 5


@pytest.mark.asyncio
async def test_queue_worker_drain_on_stop():
    """stop() must wait for the queue to flush before cancelling."""
    w = _SimpleQueueWorker()
    await w.start()
    for i in range(3):
        await w.enqueue(f"drain-{i}")
    # Stop immediately — drain should still flush.
    await w.stop()

    assert w.handled == [f"drain-{i}" for i in range(3)]


@pytest.mark.asyncio
async def test_isolate_helper_records_success_and_failure():
    """The _isolate helper bumps processed on success, failed on swallowed exc."""
    class _IsolateUser(BackgroundWorker):
        name = "isolate-user"

    w = _IsolateUser()

    async def good():
        return None

    async def bad():
        raise RuntimeError("boom")

    assert (await w._isolate(good())) is True
    assert (await w._isolate(bad()))  is False
    assert w.stats() == {"processed": 1, "failed": 1}
