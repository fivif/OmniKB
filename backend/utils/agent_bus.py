"""Global agent activity event bus.

Publish/subscribe pattern over asyncio queues.  All running agents (web_agent,
jshook_client, orchestrator, embedder …) call :func:`emit` to broadcast
structured events.  Connected SSE clients subscribe and receive a live feed.

Usage
-----
    # Producer (in any async or sync context):
    from utils.agent_bus import emit
    emit("正在打开页面…", kind="progress", agent="agent_browser", task_id="abc")

    # Consumer (in SSE handler):
    from utils.agent_bus import subscribe, unsubscribe
    q = subscribe()
    try:
        msg = await asyncio.wait_for(q.get(), timeout=20.0)
        yield f"data: {msg}\\n\\n"
    finally:
        unsubscribe(q)
"""
from __future__ import annotations

import json
import logging
import time
from asyncio import Queue, QueueFull
from typing import Literal

logger = logging.getLogger(__name__)

EventKind = Literal["info", "success", "warning", "error", "progress"]

# Agent display metadata: (label, icon)
AGENT_META: dict[str, tuple[str, str]] = {
    "agent_browser": ("agent-browser", "[WEB]"),
    "jshook":        ("jshookmcp",     "[JS]"),
    "scrapling":     ("scrapling",     "[CRAWL]"),
    "llm":           ("LLM",           "[LLM]"),
    "embedder":      ("Embedder",      "[EMB]"),
    "orchestrator":  ("Orchestrator",  "[ORCH]"),
    "doc_agent":     ("DocAgent",      "[DOC]"),
    "media_agent":   ("MediaAgent",    "[MEDIA]"),
    "vision_agent":  ("VisionAgent",   "[VISION]"),
    "system":        ("System",        "[SYS]"),
    "ingest":        ("Ingest",        "[INGEST]"),
    "wiki":          ("Wiki",          "[WIKI]"),
}

_subscribers: list[Queue[str]] = []


def subscribe(maxsize: int = 500) -> "Queue[str]":
    """Return a new subscriber queue. Call :func:`unsubscribe` when done."""
    q: Queue[str] = Queue(maxsize=maxsize)
    _subscribers.append(q)
    return q


def unsubscribe(q: "Queue[str]") -> None:
    """Remove a subscriber queue."""
    try:
        _subscribers.remove(q)
    except ValueError:
        pass


def emit(
    message: str,
    kind: EventKind = "info",
    agent: str = "system",
    task_id: str | None = None,
    meta: dict | None = None,
) -> None:
    """Broadcast an event to all active subscribers (non-blocking).

    Safe to call from both sync and async code.  Queues that are full
    (i.e., a stale disconnected client) are silently dropped.
    """
    label, icon = AGENT_META.get(agent, (agent, "[SYS]"))
    payload = {
        "t": int(time.time() * 1000),
        "msg": message,
        "kind": kind,
        "agent": agent,
        "label": label,
        "icon": icon,
    }
    if task_id:
        payload["task_id"] = task_id
    if meta:
        payload.update(meta)

    data = json.dumps(payload, ensure_ascii=False)
    dead: list["Queue[str]"] = []
    for q in _subscribers:
        try:
            q.put_nowait(data)
        except QueueFull:
            dead.append(q)

    for q in dead:
        unsubscribe(q)
        logger.debug("agent_bus: dropped full queue (disconnected client)")
