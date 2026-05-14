"""GET /metrics/cache — Prompt-cache hit-rate observability.

Exposes the data written by :func:`agent_core.cache.log_cache_stats`.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from agent_core.cache import cache_hit_rate

router = APIRouter()


@router.get("/cache", tags=["metrics"])
async def get_cache_metrics(
    window: int | None = Query(
        default=3600,
        ge=0,
        description="Aggregation window in seconds; 0 = no window (read everything).",
    ),
):
    """Return cumulative cache hit-rate statistics.

    ``window=0`` means lifetime aggregation; default 3600 = last hour.
    """
    if window == 0:
        return cache_hit_rate(window_seconds=None)
    return cache_hit_rate(window_seconds=window)
