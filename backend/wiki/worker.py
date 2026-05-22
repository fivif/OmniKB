"""Wiki worker — async consumer for ingest / lint / save events.

Architecture
------------
The worker is a single background coroutine fed by an ``asyncio.Queue``.
That gives us:

- **Back-pressure**: bursty ingests (folder import, web crawl) don't
  fan-out into N parallel LLM calls; events queue up and are processed
  one at a time.
- **Decoupling**: ingest pipeline only does ``await
  worker.enqueue(...)``; failures inside the worker never bubble back
  into the ingest hot-path.
- **Clean shutdown**: ``stop()`` flushes the queue (or honours a
  drain-timeout) and cancels the consumer, so the FastAPI lifespan can
  end deterministically.

P1 was a stub. P2+ delegates the heavy lifting to
:class:`wiki.generator.WikiGenerator`, which runs the two-step
analysis-then-generation chain. The worker still keeps an audit
trail (``wiki_events`` row + greppable ``log.md`` line) for every
event so the UI / debugger can see worker activity even when
generation is disabled or fails.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from storage.metadata_db import append_wiki_event
from workers import BackgroundWorker

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WikiEvent:
    """Unit of work the wiki worker consumes.

    The fields are intentionally a superset of what ``append_wiki_event``
    needs so the worker can also reach the LLM ingest pipeline in P2
    (with ``raw_text`` / ``source_metadata``) without another schema
    change.
    """
    kind: str                                  # 'ingest' | 'lint' | 'query_save' | 'manual_edit'
    source_id: str | None = None
    summary: str = ""
    raw_text: str | None = None                # full source body — only used by P2 LLM step
    source_metadata: dict[str, Any] = field(default_factory=dict)


class WikiWorker(BackgroundWorker):
    """Single-consumer async worker over ``data/wiki/`` and DB tables.

    Queue-driven: producers push :class:`WikiEvent` instances via
    :meth:`enqueue`; the inherited :meth:`start`/:meth:`stop` lifecycle
    spawns / cancels a single consumer ``asyncio.Task`` that pulls from
    that queue. We override :meth:`_run` for full custody of the wait
    semantics and :meth:`_drain` to flush in-flight events on shutdown.
    """

    name = "wiki-worker"
    DRAIN_TIMEOUT_S = 30.0

    # Queue depth. Picked deliberately small — wiki maintenance is
    # CPU + LLM bound, NOT throughput bound. If the queue fills up
    # something is wrong (huge folder import) and we'd rather drop new
    # work and log loudly than silently fall hours behind.
    QUEUE_MAX = 256

    def __init__(
        self,
        data_dir: str | Path,
        *,
        generator: Any | None = None,
    ):
        super().__init__()
        self._data_dir = Path(data_dir).expanduser()
        self._queue: asyncio.Queue[WikiEvent] = asyncio.Queue(maxsize=self.QUEUE_MAX)
        # Lazy-built — first event triggers construction. Keeps the
        # worker importable without dragging the LLM stack into module
        # init time (see the test harness).
        self._generator = generator

    # ── public producer API ────────────────────────────────────

    async def enqueue(self, event: WikiEvent) -> bool:
        """Submit an event. Returns False (and logs) when the queue is full
        — callers should treat that as 'fire and forget' rather than
        propagating to the user-facing request."""
        if not self.is_running:
            self._logger.warning("enqueue called before start(); dropping %s", event.kind)
            return False
        try:
            self._queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            self._logger.error(
                "queue full (%d items) — dropping %s event for %s",
                self._queue.qsize(), event.kind, event.source_id,
            )
            return False

    def stats(self) -> dict[str, int]:
        # Augment the base stats with the queue depth (queue-specific).
        return {
            "queued": self._queue.qsize(),
            **super().stats(),
        }

    # ── lifecycle hooks (override base) ────────────────────────

    async def _drain(self) -> None:
        """Wait for the queue to flush before stop() forces cancel.

        Inherited stop() wraps this in a DRAIN_TIMEOUT_S guard.
        """
        await self._queue.join()

    # ── consumer loop ──────────────────────────────────────────

    async def _run(self) -> None:
        self._logger.debug("consumer loop entered")
        while True:
            try:
                # Use a short timeout instead of pure await so the loop
                # can notice _stopping even when no events are coming.
                try:
                    event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    if self._should_stop() and self._queue.empty():
                        return
                    continue
            except asyncio.CancelledError:
                return

            try:
                await self._handle_event(event)
                self._processed += 1
            except Exception as exc:  # noqa: BLE001 — never let one event take the worker down
                self._failed += 1
                self._logger.exception("handler raised on %s: %s", event.kind, exc)
            finally:
                self._queue.task_done()

    # ── handler ────────────────────────────────────────────────

    def _get_generator(self):
        """Lazy-build the generator on first event so unit tests that
        never enqueue real work can construct a worker without dragging
        in the LLM stack."""
        if self._generator is not None:
            return self._generator
        # Imported lazily — see class docstring.
        from wiki.generator import WikiGenerator
        try:
            from config import settings as _settings
            self._generator = WikiGenerator(
                self._data_dir,
                source_truncate_chars=_settings.wiki_max_source_chars,
                generation_concurrency=_settings.wiki_generation_concurrency,
            )
        except Exception:
            # Fallback to defaults if settings can't load — keeps the
            # worker functional in environments without a config file.
            self._generator = WikiGenerator(self._data_dir)
        return self._generator

    async def _handle_event(self, event: WikiEvent) -> None:
        """Per-event work. Always:

        1. Records a structured row in ``wiki_events``.
        2. Appends a greppable line to ``data/wiki/log.md``.

        Then dispatches by ``event.kind``:

        - ``ingest`` (default): runs the two-step LLM generator. If
          ``raw_text`` is empty (legacy callers, lint events) the
          generator step is skipped — we still want the audit trail.
        - other kinds: P5 will add lint / query_save handlers; for now
          we just log and continue.
        """
        # ── 1. Audit trail (always) ────────────────────────────
        try:
            await append_wiki_event(
                kind=event.kind,
                source_id=event.source_id,
                summary=event.summary or f"({event.kind})",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("wiki worker: failed to record DB event: %s", exc)

        await self._append_markdown_log(event)

        # ── 2. Dispatch (best-effort; never raises) ────────────
        if event.kind != "ingest":
            logger.debug("wiki worker: kind=%s — no generator path yet", event.kind)
            return

        if not event.raw_text:
            logger.debug("wiki worker: ingest event has no raw_text; skipping generator")
            return

        # Master kill-switch — keep audit trail but skip the LLM call
        # for cost-sensitive deploys / CI runs.
        try:
            from config import settings as _settings
            if not getattr(_settings, "wiki_enabled", True):
                logger.debug("wiki worker: settings.wiki_enabled=False; skipping generator")
                return
        except Exception:
            pass

        try:
            gen = self._get_generator()
            result = await gen.generate(
                source_id=event.source_id or "unknown",
                source_text=event.raw_text,
                source_metadata=event.source_metadata or {},
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("wiki worker: generator crashed: %s", exc)
            try:
                await append_wiki_event(
                    kind="ingest_failed",
                    source_id=event.source_id,
                    summary=f"generator crashed: {type(exc).__name__}: {exc}",
                )
            except Exception:  # noqa: BLE001
                pass
            return

        if result.error:
            logger.warning(
                "wiki worker: generation failed for %s: %s",
                event.source_id, result.error,
            )
            try:
                await append_wiki_event(
                    kind="ingest_failed",
                    source_id=event.source_id,
                    summary=result.error,
                )
            except Exception:  # noqa: BLE001
                pass
            return

        logger.info(
            "wiki worker: %s → %d created / %d updated / %d failed / %d edges",
            event.source_id,
            result.pages_created,
            result.pages_updated,
            result.pages_failed,
            result.edges_added,
        )

    async def _append_markdown_log(self, event: WikiEvent) -> None:
        log_path = self._data_dir / "wiki" / "log.md"
        # If the bootstrap step hasn't run yet (e.g. tests calling the
        # worker directly), don't crash — the log entry is best-effort.
        if not log_path.parent.exists():
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                logger.debug("wiki log: mkdir failed (%s); skipping append", exc)
                return

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        line = f"\n## [{ts}] {event.kind} | {event.summary or '(no summary)'}\n"
        if event.source_id:
            line += f"- source: `{event.source_id}`\n"

        # Run the blocking write in a thread to avoid stalling the event
        # loop on slow filesystems (NFS, network mounts).
        await asyncio.to_thread(_atomic_append, log_path, line)


def _atomic_append(path: Path, content: str) -> None:
    """Append ``content`` to ``path``, creating the file if missing.

    'Atomic' here means the file always exists with sane content if the
    process crashes mid-write — we never write partial UTF-8 because
    Python writes bytes whole. We deliberately don't lock: the worker is
    single-consumer so there's no contention.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(content)
