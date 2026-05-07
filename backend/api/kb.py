from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from storage.file_store import delete_file
from storage.metadata_db import (
    count_chunks,
    count_sources,
    delete_source,
    get_all_tags,
    get_source,
    list_chunks_by_source,
    list_sources,
    update_source_tags,
)
from storage.vector_store import delete_by_source_id

router = APIRouter()


class TagsUpdateRequest(BaseModel):
    tags: list[str]


@router.get("/sources")
async def get_sources(
    limit: int = 50,
    offset: int = 0,
    filter_tag: str | None = None,
):
    sources = await list_sources(limit=limit, offset=offset, filter_tag=filter_tag)
    return {"sources": sources, "limit": limit, "offset": offset}


@router.get("/sources/{source_id}")
async def get_source_detail(source_id: str):
    src = await get_source(source_id)
    if not src:
        raise HTTPException(status_code=404, detail="Source not found")
    return src


@router.get("/sources/{source_id}/chunks")
async def get_source_chunks(source_id: str, limit: int = 50, offset: int = 0):
    chunks = await list_chunks_by_source(source_id, limit=limit, offset=offset)
    return {"source_id": source_id, "chunks": chunks}


@router.patch("/sources/{source_id}/tags")
async def update_tags(source_id: str, req: TagsUpdateRequest):
    src = await get_source(source_id)
    if not src:
        raise HTTPException(status_code=404, detail="Source not found")
    await update_source_tags(source_id, req.tags)
    return {"source_id": source_id, "tags": req.tags}


@router.delete("/sources/{source_id}")
async def delete_source_endpoint(source_id: str):
    src = await get_source(source_id)
    if not src:
        raise HTTPException(status_code=404, detail="Source not found")

    await delete_by_source_id(source_id)
    await delete_source(source_id)
    delete_file(source_id)

    return {"status": "deleted", "source_id": source_id}


@router.get("/tags")
async def list_all_tags():
    """Return all distinct tags used across sources."""
    return {"tags": await get_all_tags()}


@router.get("/stats")
async def get_stats():
    return {
        "total_sources": await count_sources(),
        "total_chunks": await count_chunks(),
    }
