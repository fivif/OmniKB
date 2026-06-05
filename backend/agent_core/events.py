"""Lifecycle events + EventStream broadcast bus.

Defines the 9 typed events emitted by ``run_loop``:

  agent_start
  turn_start
  message_start
  message_update      ← high-frequency; SSE consumers should rAF-batch
  message_end
  tool_execution_start
  tool_execution_end
  turn_end
  agent_end

EventStream is a multi-subscriber broadcast queue. ``publish()`` fans out
non-blockingly; subscribers consume via ``await q.get()``. Each event carries
a process-global monotonic ``seq`` so that SSE clients can resume after
disconnect via ``Last-Event-ID``.

Backward compatibility: events are *also* mirrored to ``utils.agent_bus.emit``
in flat shape so existing v1 SSE consumers (the bottom Agent Console) keep
working untouched.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)


EventType = Literal[
    "agent_start", "turn_start",
    "message_start", "message_update", "message_end",
    "tool_execution_start", "tool_execution_end",
    "turn_end", "agent_end",
    "wiki_analysis_start", "wiki_analysis_complete",
    "wiki_page_generating", "wiki_page_created", "wiki_page_error",
    "wiki_batch_start", "wiki_sync_complete", "wiki_sync_error",
    "ingest_start", "ingest_progress", "ingest_complete", "ingest_error",
]

EVENT_TYPES: tuple[str, ...] = (
    "agent_start", "turn_start",
    "message_start", "message_update", "message_end",
    "tool_execution_start", "tool_execution_end",
    "turn_end", "agent_end",
    "wiki_analysis_start", "wiki_analysis_complete",
    "wiki_page_generating", "wiki_page_created", "wiki_page_error",
    "wiki_batch_start", "wiki_sync_complete", "wiki_sync_error",
    "ingest_start", "ingest_progress", "ingest_complete", "ingest_error",
)


_seq_counter = itertools.count(1)


def _next_seq() -> int:
    return next(_seq_counter)


@dataclass
class AgentEvent:
    """One typed lifecycle event.

    ``seq`` is auto-assigned monotonically. ``timestamp`` defaults to now.
    Both are populated in ``__post_init__`` so callers can construct events
    with bare ``type`` + ``task_id`` + ``data``.
    """
    type: EventType
    task_id: str
    data: dict[str, Any] = field(default_factory=dict)
    seq: int = 0
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if self.seq == 0:
            self.seq = _next_seq()
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def to_sse(self) -> str:
        """Serialise to SSE wire format with ``id:`` / ``data:`` lines.

        We DELIBERATELY do NOT emit the ``event: <type>`` line: the frontend
        in ``frontend/js/agent-console.js`` listens to the default
        ``message`` channel and does the dispatch in JS via
        ``JSON.parse(e.data).type``. Emitting ``event:`` would force
        EventSource to route every frame to a named handler instead, silently
        breaking the live agent console. The wire format is intentional —
        any future move to typed events must be coordinated frontend + backend.
        """
        payload = {
            "type": self.type,
            "task_id": self.task_id,
            "seq": self.seq,
            "timestamp": self.timestamp,
            "data": self.data,
        }
        body = json.dumps(payload, ensure_ascii=False)
        return f"id: {self.seq}\ndata: {body}\n\n"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "task_id": self.task_id,
            "seq": self.seq,
            "timestamp": self.timestamp,
            "data": dict(self.data),
        }


# ── Module-level singleton ─────────────────────────────────────────
# The app lifespan sets this once via set_event_stream().  Consumers call
# get_event_stream() instead of importing main.FastAPI.app, which would
# trigger the __main__ / main double-import problem.

_event_stream: EventStream | None = None


def get_event_stream() -> EventStream:
    """Return the process-wide EventStream singleton.

    If the lifespan hasn't set one yet (e.g. during early startup or tests),
    a new *isolated* stream is created automatically.  Events published to
    an isolated stream won't reach any SSE subscribers, but the agent loop
    can still run without crashing.
    """
    global _event_stream
    if _event_stream is None:
        _event_stream = EventStream()
        logger.warning(
            "get_event_stream: no singleton set yet — created isolated EventStream"
        )
    return _event_stream


def set_event_stream(stream: EventStream) -> None:
    """Inject the shared EventStream (called by app lifespan)."""
    global _event_stream
    _event_stream = stream


class EventStream:
    """Multi-subscriber async broadcast queue for AgentEvents.

    Each subscriber receives its own bounded ``asyncio.Queue``. ``publish()``
    fans out non-blockingly: a full subscriber queue means the consumer is
    behind, so we drop the new event for that subscriber (it will resync via
    ``Last-Event-ID`` on reconnect).

    Usage::

        stream = EventStream()
        q = stream.subscribe()
        try:
            while True:
                evt = await q.get()
                yield evt.to_sse()
        finally:
            stream.unsubscribe(q)
    """

    def __init__(self, max_queue: int = 1000):
        self._max_queue = max_queue
        self._subs: list[asyncio.Queue[AgentEvent]] = []
        self._dropped_count: int = 0  # for /metrics observability

    def subscribe(self) -> "asyncio.Queue[AgentEvent]":
        q: asyncio.Queue[AgentEvent] = asyncio.Queue(maxsize=self._max_queue)
        self._subs.append(q)
        return q

    def unsubscribe(self, q: "asyncio.Queue[AgentEvent]") -> None:
        try:
            self._subs.remove(q)
        except ValueError:
            pass

    async def publish(self, event: AgentEvent) -> None:
        """Fan-out to all subscribers; drop on full queue."""
        n_subs = len(self._subs)
        if n_subs == 0:
            logger.warning(
                "EventStream.publish: 无订阅者！ seq=%d type=%s task=%s",
                event.seq, event.type, event.task_id,
            )
        logger.debug(
            "EventStream.publish: seq=%d type=%s task=%s subs=%d",
            event.seq, event.type, event.task_id, n_subs,
        )
        # iterate copy so unsubscribe during publish doesn't break us
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                self._dropped_count += 1
                logger.debug(
                    "EventStream subscriber queue full (seq=%d type=%s); dropping",
                    event.seq, event.type,
                )

        # Mirror to legacy agent_bus for v1 SSE consumers
        try:
            from utils.agent_bus import emit
            kind = _event_kind_hint(event)
            emit(
                _event_message_hint(event),
                kind=kind,
                agent="orchestrator",
                task_id=event.task_id,
                meta={"v2_seq": event.seq, "v2_type": event.type},
            )
        except Exception as exc:
            logger.debug("v1 mirror failed (non-fatal): %s", exc)

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    @property
    def dropped_count(self) -> int:
        return self._dropped_count


def _event_kind_hint(event: AgentEvent) -> str:
    """Map a typed event to v1 ``kind`` ('progress'/'success'/'error'/...)."""
    if event.type == "agent_end":
        status = (event.data or {}).get("final_status")
        if status == "completed":
            return "success"
        if status in {"failed", "error"}:
            return "error"
        return "info"
    if event.type == "tool_execution_end":
        if (event.data or {}).get("status") == "error":
            return "error"
        return "success"
    if event.type in {"agent_start", "turn_start", "message_start"}:
        return "info"
    if event.type == "wiki_page_created":
        return "success"
    if event.type == "wiki_sync_complete":
        return "success"
    if event.type in {"wiki_page_error", "wiki_sync_error", "ingest_error"}:
        return "error"
    if event.type == "ingest_start":
        return "info"
    if event.type == "ingest_progress":
        return "progress"
    if event.type == "ingest_complete":
        return "success"
    return "progress"


def _event_message_hint(event: AgentEvent) -> str:
    """Brief human-readable summary for the v1 mirror (≤ 120 chars)."""
    d = event.data or {}
    t = event.type
    if t == "agent_start":
        return f"agent_start  model={d.get('model','?')}"
    if t == "turn_start":
        return f"turn_start   turn={d.get('turn','?')}"
    if t == "message_start":
        return f"message_start  role={d.get('role','assistant')}"
    if t == "message_update":
        delta = d.get("delta")
        if delta:
            sample = delta[:40].replace("\n", " ")
            return f"… {sample}"
        if d.get("tool_call_delta"):
            return "tool_call streaming"
        return "msg update"
    if t == "message_end":
        return f"message_end  tool_calls={len(d.get('tool_calls') or [])}"
    if t == "tool_execution_start":
        return f"[TOOL] {d.get('tool_name','?')}({(d.get('args_preview') or '')[:60]})"
    if t == "tool_execution_end":
        return f"[OK] {d.get('tool_name','?')}  status={d.get('status','?')}  {d.get('duration_ms','?')}ms"
    if t == "turn_end":
        c = d.get("compaction_triggered")
        return f"turn_end  duration={d.get('duration_ms','?')}ms  compacted={c}"
    if t == "agent_end":
        return f"agent_end  status={d.get('final_status','?')}  turns={d.get('total_turns','?')}"
    if t == "wiki_analysis_start":
        return f"Wiki: analyzing source {d.get('title','')}"
    if t == "wiki_analysis_complete":
        return f"Wiki: analysis done, {d.get('plan_pages',0)} pages planned"
    if t == "wiki_page_generating":
        return f"Wiki: generating {d.get('page_id','')}"
    if t == "wiki_page_created":
        return f"Wiki: created {d.get('page_id','')}"
    if t == "wiki_page_error":
        return f"Wiki: page error {d.get('page_id','')}: {d.get('error','')[:120]}"
    if t == "wiki_batch_start":
        return f"Wiki: generating {d.get('batch_size',0)} pages"
    if t == "wiki_sync_complete":
        return f"Wiki sync done: {d.get('pages_created',0)} created"
    if t == "wiki_sync_error":
        return f"Wiki sync error: {d.get('error','')[:120]}"
    if t == "ingest_start":
        return f"Ingest started: {d.get('title','')}"
    if t == "ingest_progress":
        return f"Ingest: {d.get('stage','')} — {d.get('detail','')}"
    if t == "ingest_complete":
        return f"Ingest done: {d.get('title','')} — {d.get('wiki_pages',0)} wiki pages"
    if t == "ingest_error":
        return f"Ingest error: {d.get('title','')} — {str(d.get('error',''))[:80]}"
    return t
