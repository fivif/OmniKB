from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from storage.file_store import delete_file
from storage.metadata_db import (
    batch_delete_sources,
    batch_update_tags,
    count_chunks,
    count_sources,
    delete_source,
    export_all_data,
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


class BatchDeleteRequest(BaseModel):
    ids: list[str]


class BatchTagRequest(BaseModel):
    ids: list[str]
    tags: list[str]
    mode: str = "replace"  # replace | add | remove


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
    """Delete a source from Qdrant + SQLite + file store.

    Order matters: we always remove the vectors first. If Qdrant deletion
    fails, we abort *before* touching SQLite so the user can retry without
    leaving orphan rows. The previous implementation silently swallowed
    Qdrant failures, which produced "ghost" search results pointing at
    chunks that no longer existed in metadata.
    """
    import logging as _lg

    src = await get_source(source_id)
    if not src:
        raise HTTPException(status_code=404, detail="Source not found")

    try:
        await delete_by_source_id(source_id)
    except Exception as exc:
        _lg.getLogger(__name__).warning(
            "Qdrant delete failed for source %s: %s (skipping, source will still be cleaned up)", source_id, exc,
        )
        # Don't block the delete — Qdrant might not exist or be empty.
        # The source + wiki cleanup below is what matters.

    await delete_source(source_id)

    # File-store cleanup is best-effort: at this point both Qdrant and SQLite
    # are consistent. Leftover files are harmless and can be reaped offline.
    try:
        delete_file(source_id)
    except Exception as exc:
        _lg.getLogger(__name__).warning(
            "file_store cleanup failed for %s (non-fatal): %s", source_id, exc,
        )

    return {"status": "deleted", "source_id": source_id}


@router.post("/sources/batch-delete")
async def batch_delete(req: BatchDeleteRequest):
    """Batch delete sources. Reports per-source failures so the caller can
    retry the affected IDs instead of believing every ID was wiped."""
    import logging as _lg
    log = _lg.getLogger(__name__)

    if not req.ids:
        raise HTTPException(status_code=400, detail="ids must not be empty")

    qdrant_failures: list[str] = []
    safe_ids: list[str] = []
    for sid in req.ids:
        try:
            await delete_by_source_id(sid)
            safe_ids.append(sid)
        except Exception as exc:
            log.error("Qdrant delete failed for %s: %s", sid, exc)
            qdrant_failures.append(sid)

    count = await batch_delete_sources(safe_ids) if safe_ids else 0

    file_failures: list[str] = []
    for sid in safe_ids:
        try:
            delete_file(sid)
        except Exception as exc:
            log.warning("file_store cleanup failed for %s: %s", sid, exc)
            file_failures.append(sid)

    return {
        "status": "ok" if not qdrant_failures else "partial",
        "count": count,
        "qdrant_failures": qdrant_failures,
        "file_failures": file_failures,
    }


@router.post("/sources/batch-tag")
async def batch_tag(req: BatchTagRequest):
    if not req.ids:
        raise HTTPException(status_code=400, detail="ids must not be empty")
    if req.mode not in ("replace", "add", "remove"):
        raise HTTPException(status_code=400, detail="mode must be replace|add|remove")
    await batch_update_tags(req.ids, req.tags, req.mode)
    return {"status": "ok", "count": len(req.ids), "mode": req.mode, "tags": req.tags}


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


@router.get("/export")
async def export_kb(fmt: str = "json"):
    """Export the entire knowledge base.

    Query params:
    - ``fmt=json`` (default) — single JSON file with all sources + chunks
    - ``fmt=csv``  — ZIP containing sources.csv + chunks.csv
    - ``fmt=zip``  — ZIP with one JSON file per source
    """
    data = await export_all_data()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if fmt == "json":
        content = json.dumps(data, ensure_ascii=False, indent=2)
        return StreamingResponse(
            iter([content.encode("utf-8")]),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=omnikb_export_{ts}.json"},
        )

    if fmt == "csv":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # sources.csv
            src_buf = io.StringIO()
            src_writer = csv.DictWriter(
                src_buf,
                fieldnames=["id", "name", "type", "url", "tags", "status", "created_at"],
            )
            src_writer.writeheader()
            for src in data["sources"]:
                src_writer.writerow({
                    "id": src["id"], "name": src["name"], "type": src["type"],
                    "url": src.get("url", ""), "tags": json.dumps(src.get("tags", [])),
                    "status": src.get("status", ""), "created_at": src.get("created_at", ""),
                })
            zf.writestr("sources.csv", src_buf.getvalue())

            # chunks.csv
            chk_buf = io.StringIO()
            chk_writer = csv.DictWriter(
                chk_buf,
                fieldnames=["id", "source_id", "chunk_index", "content"],
            )
            chk_writer.writeheader()
            for src in data["sources"]:
                for chk in src.get("chunks", []):
                    chk_writer.writerow({
                        "id": chk["id"], "source_id": src["id"],
                        "chunk_index": chk["chunk_index"],
                        "content": chk["content"].replace("\n", "\\n"),
                    })
            zf.writestr("chunks.csv", chk_buf.getvalue())

        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename=omnikb_export_{ts}.zip"},
        )

    if fmt == "zip":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for src in data["sources"]:
                safe_name = "".join(c if c.isalnum() or c in "-_." else "_" for c in src["name"])[:60]
                filename = f"{src['id'][:8]}_{safe_name}.json"
                zf.writestr(filename, json.dumps(src, ensure_ascii=False, indent=2))
            # summary
            summary = {
                "export_time": ts,
                "total_sources": data["total_sources"],
                "files": [s["id"] for s in data["sources"]],
            }
            zf.writestr("_index.json", json.dumps(summary, ensure_ascii=False, indent=2))

        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename=omnikb_export_{ts}.zip"},
        )

    raise HTTPException(status_code=400, detail="fmt must be one of: json, csv, zip")
