"""Agent activity SSE stream endpoint.

GET /agent/events — Server-Sent Events stream of all agent activity.
Each event is a JSON payload from :mod:`utils.agent_bus`.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from utils.agent_bus import subscribe, unsubscribe

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

