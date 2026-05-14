from __future__ import annotations

from fastapi import APIRouter, Query

from storage.metadata_db import list_mcp_logs

router = APIRouter()


@router.get("")
async def get_mcp_logs(
    limit: int = Query(50, ge=1, le=200, description="Number of records to return"),
    tool: str | None = Query(None, description="Filter by tool name"),
):
    """Return recent MCP tool call logs, newest first."""
    return {"logs": await list_mcp_logs(limit=limit, tool=tool)}
