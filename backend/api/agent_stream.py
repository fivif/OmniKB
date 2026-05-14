"""Agent activity SSE stream endpoint.

GET /agent/events — Server-Sent Events stream of all agent activity.
Each event is a JSON payload from :mod:`utils.agent_bus`.

POST /agent/{task_id}/steer — Inject a steering or follow-up message
into a running agent. See :mod:`backend.agent_core.steering`.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from typing import Literal

from utils.agent_bus import subscribe, unsubscribe
from agent_core import steering as _steering

router = APIRouter()

_PING = 'data: {"ping":1}\n\n'


@router.get("/events", tags=["agent"])
async def agent_events(request: Request):
    """SSE stream of all agent activity events.

    Connect with ``EventSource('/agent/events')`` in the browser.
    Each ``data:`` message is a JSON object:

    .. code-block:: json

        {
          "t":     1714000000000,
          "msg":   "正在打开页面…",
          "kind":  "progress",
          "agent": "agent_browser",
          "label": "agent-browser",
          "icon":  "🌐",
          "task_id": "abc123"
        }

    ``kind`` is one of: ``"info"`` ``"success"`` ``"warning"`` ``"error"`` ``"progress"``
    """
    async def generate():
        q = subscribe()
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=25.0)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield _PING
        finally:
            unsubscribe(q)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/sessions", tags=["agent"])
async def list_agent_sessions(limit: int = 50, offset: int = 0):
    """List web-agent ingestion sessions (newest first)."""
    from storage.metadata_db import list_web_sessions
    return await list_web_sessions(limit=limit, offset=offset)


@router.get("/sessions/{session_id}", tags=["agent"])
async def get_agent_session(session_id: str):
    """Get a session's metadata + full message history."""
    from fastapi import HTTPException
    from storage.metadata_db import get_web_session, list_session_messages
    sess = await get_web_session(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="session not found")
    msgs = await list_session_messages(session_id)
    return {"session": sess, "messages": msgs}


# ─── Steering endpoint (M2.3) ────────────────────────────────────────


class SteerRequest(BaseModel):
    """Body of POST /agent/{task_id}/steer."""
    kind: Literal["steer", "follow_up"] = Field(
        default="steer",
        description='"steer" (drain before next LLM call) or "follow_up" (wake the agent after it stopped)',
    )
    content: str = Field(..., min_length=1, max_length=10_000)
    priority: Literal["normal", "interrupt"] = Field(
        default="normal",
        description='"interrupt" cancels the in-flight LLM stream; "normal" waits for current turn to finish.',
    )


@router.post("/{task_id}/steer", tags=["agent"])
async def steer_agent(task_id: str, req: SteerRequest):
    """Inject a steering or follow-up message into a running agent task.

    Returns 404 if no active task with this ID, 409 if an interrupt is
    already pending (don't pile up multiple interrupts).
    """
    queues = _steering.get_queues(task_id)
    if queues is None:
        return JSONResponse(
            {"accepted": False, "reason": "task not active"},
            status_code=404,
        )

    target_q = queues.steering if req.kind == "steer" else queues.follow_up

    if req.priority == "interrupt" and target_q.is_interrupt_pending():
        return JSONResponse(
            {"accepted": False, "reason": "interrupt already pending"},
            status_code=409,
        )

    new_size = await target_q.push(req.content, priority=req.priority)
    # ``will_apply_at_turn`` requires loop visibility; v2 will populate this
    # via AgentState.turn. For now, return queue depth + null hint.
    return {
        "accepted": True,
        "queue": req.kind,
        "queue_size": new_size,
        "will_apply_at_turn": None,
        "interrupt_pending": target_q.is_interrupt_pending(),
    }


@router.get("/active-tasks", tags=["agent"])
async def list_active_tasks():
    """List task_ids currently registered for steering (i.e. mid-run)."""
    return {"task_ids": _steering.active_task_ids()}


# ─── PC.1: Typed v2 event stream ─────────────────────────────────────


@router.get("/v2/events", tags=["agent"])
async def agent_events_v2(
    request: Request,
    task_id: str | None = None,
):
    """Server-Sent Events stream of typed AgentEvents.

    Each line block is a complete SSE record:

    .. code-block:: text

        event: turn_start
        id: 42
        data: {"type":"turn_start","task_id":"...","seq":42,"timestamp":..,"data":{"turn":3,...}}

    Query params:
    * ``task_id`` — filter to one task; omit to subscribe to all activity.

    The endpoint is also reachable via HEAD for client-side protocol
    detection (``frontend/js/app.js::detectOmnikbV2``).
    """
    # HEAD probe: just acknowledge availability
    if request.method == "HEAD":
        return JSONResponse({"v2": True})

    stream = getattr(request.app.state, "event_stream", None)
    if stream is None:
        return JSONResponse(
            {"detail": "event stream not initialised"}, status_code=503,
        )

    import logging as _agc_log
    _agc_log.getLogger(__name__).info(
        "v2 SSE: new subscriber (total=%d)", stream.subscriber_count,
    )
    async def gen():
        q = stream.subscribe()
        import logging as _agc_log2
        _agc_log2.getLogger(__name__).info(
            "v2 SSE: subscriber connected (total=%d)", stream.subscriber_count,
        )
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=25.0)
                except asyncio.TimeoutError:
                    yield "event: ping\ndata: {}\n\n"
                    continue
                if task_id and ev.task_id != task_id:
                    continue
                yield ev.to_sse()
        finally:
            stream.unsubscribe(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.head("/v2/events", tags=["agent"], include_in_schema=False)
async def agent_events_v2_probe():
    """HEAD probe used by frontend to detect v2 protocol availability."""
    return JSONResponse({"v2": True})

