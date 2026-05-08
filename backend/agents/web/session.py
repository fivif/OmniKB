"""WebSession — SQLite-backed conversation persistence for the web agent loop.

Each ingest task gets its own session. Messages are appended one row per turn
so resume is cheap and a session can be inspected mid-flight.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class WebSession:
    """A persistent conversation log keyed by session_id."""

    def __init__(self, session_id: str, task_id: str | None = None):
        self.id = session_id
        self.task_id = task_id

    @classmethod
    async def create(cls, task_id: str | None = None, cwd: str | None = None) -> "WebSession":
        from storage.metadata_db import create_web_session
        sid = str(uuid.uuid4())
        await create_web_session({
            "id": sid,
            "task_id": task_id,
            "cwd": cwd,
            "status": "running",
        })
        return cls(sid, task_id=task_id)

    @classmethod
    async def open(cls, session_id: str) -> "WebSession | None":
        from storage.metadata_db import get_web_session
        row = await get_web_session(session_id)
        if not row:
            return None
        return cls(session_id, task_id=row.get("task_id"))

    async def append(self, role: str, content: str | None, tool_calls: Any = None) -> None:
        """Append one message. *tool_calls* is JSON-serialised if not str."""
        from storage.metadata_db import append_session_message
        tc_str: str | None = None
        if tool_calls:
            tc_str = tool_calls if isinstance(tool_calls, str) else json.dumps(tool_calls, ensure_ascii=False)
        await append_session_message(self.id, role, content, tc_str)

    async def messages(self) -> list[dict]:
        """Return rows as plain dicts (role, content, tool_calls, created_at)."""
        from storage.metadata_db import list_session_messages
        rows = await list_session_messages(self.id)
        out = []
        for r in rows:
            d = {"role": r["role"], "content": r.get("content")}
            tc = r.get("tool_calls")
            if tc:
                try:
                    d["tool_calls"] = json.loads(tc)
                except Exception:
                    d["tool_calls"] = tc
            out.append(d)
        return out

    async def set_status(self, status: str) -> None:
        from storage.metadata_db import update_session_status
        await update_session_status(self.id, status)
