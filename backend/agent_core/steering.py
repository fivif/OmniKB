"""Steering + Follow-up queues — runtime extension points for the agent loop.

Two queue types per active task:

* **SteeringQueue** — user messages injected DURING a run. Drained by the
  loop before the next ``llm_call`` (i.e. between turns). The loop checks
  ``is_interrupt_pending()`` to decide whether to cancel the in-flight LLM
  stream rather than waiting for it to finish.

* **FollowUpQueue** — messages that wake a finished agent. If the loop is
  about to exit (no more tool_calls + steering empty), but the follow-up
  queue is non-empty, the loop drains it and starts another turn.

The pattern mirrors pi-agent-core's ``steeringQueue`` / ``followUpQueue``
(see earendil-works/pi packages/agent/src/agent.ts). We use plain
``asyncio.Queue`` instead of pi's custom event emitter because we have no
need for backpressure on these (queues will hold a handful of messages at
most).

A process-global registry maps ``task_id`` → ``(steering, followup)`` so
that the FastAPI ``POST /agent/{task_id}/steer`` route can find the right
queues for a running task without having to thread state through manually.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)


SteerPriority = Literal["normal", "interrupt"]


@dataclass
class SteerMessage:
    """One steering injection from the user."""
    content: str
    priority: SteerPriority = "normal"


class _MessageQueue:
    """Lightweight async-safe queue of SteerMessages.

    Distinguished from ``asyncio.Queue`` because we want synchronous drain
    + interrupt inspection without ``await`` ceremony.
    """

    def __init__(self, name: str = ""):
        self._name = name
        self._items: list[SteerMessage] = []
        self._lock = asyncio.Lock()

    async def push(self, content: str, priority: SteerPriority = "normal") -> int:
        """Append a message. Returns new queue depth."""
        async with self._lock:
            self._items.append(SteerMessage(content=content, priority=priority))
            return len(self._items)

    def drain(self) -> list[SteerMessage]:
        """Return + clear all queued messages. Safe to call without await."""
        items = self._items
        self._items = []
        return items

    def peek(self) -> bool:
        """Non-destructive: True if any messages waiting."""
        return bool(self._items)

    def is_interrupt_pending(self) -> bool:
        return any(m.priority == "interrupt" for m in self._items)

    @property
    def size(self) -> int:
        return len(self._items)


class SteeringQueue(_MessageQueue):
    """Drained by the loop BEFORE the next LLM call (mid-run injection)."""

    def __init__(self):
        super().__init__(name="steering")


class FollowUpQueue(_MessageQueue):
    """Drained by the loop when it would otherwise exit (post-run wake)."""

    def __init__(self):
        super().__init__(name="follow_up")


@dataclass
class TaskQueues:
    """Combined handle for one active task."""
    steering: SteeringQueue = field(default_factory=SteeringQueue)
    follow_up: FollowUpQueue = field(default_factory=FollowUpQueue)


# ─── Global registry (one entry per active task) ─────────────────────

_active: dict[str, TaskQueues] = {}
_registry_lock = asyncio.Lock()


async def register(task_id: str) -> TaskQueues:
    """Idempotent: returns existing queues if task already registered."""
    async with _registry_lock:
        existing = _active.get(task_id)
        if existing is not None:
            return existing
        q = TaskQueues()
        _active[task_id] = q
        return q


async def unregister(task_id: str) -> None:
    async with _registry_lock:
        _active.pop(task_id, None)


def get_queues(task_id: str) -> TaskQueues | None:
    """Synchronous lookup (used by API endpoints to push without async)."""
    return _active.get(task_id)


def active_task_ids() -> list[str]:
    return list(_active.keys())


def clear_registry_for_tests() -> None:
    """Test-only: wipe the registry between unit tests."""
    _active.clear()
