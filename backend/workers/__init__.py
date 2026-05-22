"""Long-running async background workers.

Two flavours, both built on :class:`BackgroundWorker`:

- **Queue-driven** (e.g. :class:`wiki.worker.WikiWorker`) — fed by
  ``enqueue()`` calls from producers; the loop blocks on the queue
  until work or a stop signal arrives. Subclass overrides ``_run()``
  with full custody of the wait + dispatch logic.

- **Tick-driven** (e.g. :class:`ScheduledResearchWorker`) — runs one
  iteration of work, sleeps for ``TICK_INTERVAL_S`` (responsive to
  the stop event), repeats. Subclass overrides ``_loop_iteration()``
  and inherits the rest.

The base handles the boring bits identically for both: spawning the
asyncio.Task, wiring an ``asyncio.Event`` for graceful shutdown,
isolating exceptions inside one iteration so a single bad event /
tick never takes the worker down, counting processed / failed for
the ``stats()`` snapshot, and cancelling cleanly during ``stop()``
with a configurable drain timeout.
"""
from .base import BackgroundWorker

__all__ = ["BackgroundWorker"]
