from __future__ import annotations
import asyncio
import uuid

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from agents.doc_agent import parse_file, parse_file_async, parse_text
from agents.orchestrator import run_ingest_pipeline
from storage.file_store import save_file
from storage.metadata_db import (
    append_task_log,
    get_task,
    insert_source,
    insert_task,
    list_tasks,
    update_source_status,
    update_task,
)

router = APIRouter()


class TextIngestRequest(BaseModel):
    content: str
    title: str = "Untitled"
    tags: list[str] = []


class UrlIngestRequest(BaseModel):
    url: str
    title: str | None = None
    tags: list[str] = []
    mode: str = "smart"  # smart | auto | static | dynamic | stealth | agent_browser | jshook
    cookies: dict[str, str] | None = None  # {name: value} for authenticated pages
    # Free-text description of what to collect, used by the LLM judge.
    # If empty, tags are joined as fallback intent.
    intent: str = ""


class SiteIngestRequest(BaseModel):
    url: str
    title: str | None = None
    tags: list[str] = []
    max_pages: int = 50
    max_depth: int = 3
    mode: str = "auto"  # auto | static | dynamic | stealth
    cookies: dict[str, str] | None = None  # session cookies for authenticated sites
    # Free-text description of what to collect, used by the LLM judge.
    # If empty, tags are joined as fallback intent.
    intent: str = ""


# ── Background task runners ───────────────────────────────────

async def _run_file_task(
    source_id: str,
    task_id: str,
    file_path: str,
    file_type: str,
    extra: dict,
) -> None:
    ext = f".{file_type.lower()}"
    await append_task_log(task_id, f"📂 收到文件，类型 {file_type.upper()}")
    # Route media files (video/audio) to MediaAgent
    try:
        from agents.media_agent import is_media_file, transcribe_async
        if is_media_file(ext):
            from config import settings
            raw_doc = await transcribe_async(file_path, settings.whisper_model_size)
        else:
            raw_doc = await parse_file_async(file_path, file_type)
    except ImportError:
        # faster-whisper not installed — fall back to doc parser
        raw_doc = await parse_file_async(file_path, file_type)
    await run_ingest_pipeline(source_id, task_id, raw_doc, extra_metadata=extra)


async def _run_text_task(
    source_id: str,
    task_id: str,
    content: str,
    extra: dict,
) -> None:
    await append_task_log(task_id, f"📝 收到文本，{len(content)} 字符")
    raw_doc = parse_text(content)
    await run_ingest_pipeline(source_id, task_id, raw_doc, extra_metadata=extra)


async def _run_url_task(
    source_id: str,
    task_id: str,
    url: str,
    extra: dict,
    mode: str = "auto",
    cookies: dict | None = None,
    intent: str = "",
) -> None:
    await append_task_log(task_id, f"🌐 抓取 URL：{url}（模式：{mode}{'  意图：' + intent if intent else ''}）")
    if mode == "smart":
        from agents.web.loop import run_agent
        try:
            raw_doc = await run_agent(url=url, intent=intent, task_id=task_id)
        except Exception as exc:
            await append_task_log(task_id, f"❌ smart agent failed: {exc}")
            await update_task(task_id, "error", error=str(exc))
            await update_source_status(source_id, "error")
            return
    else:
        from agents.web_agent import fetch_url
        try:
            raw_doc = await fetch_url(url, mode=mode, cookies=cookies, intent=intent)
        except ValueError as exc:
            await append_task_log(task_id, f"🚫 页面被 LLM 判定无价值，已跳过：{exc}")
            await update_task(task_id, "done")
            await update_source_status(source_id, "done")
            return
    await run_ingest_pipeline(source_id, task_id, raw_doc, extra_metadata=extra)


async def _run_site_task(
    source_id: str,
    task_id: str,
    url: str,
    max_pages: int,
    max_depth: int,
    mode: str,
    extra: dict,
    cookies: dict | None = None,
    intent: str = "",
) -> None:
    """BFS site crawl: each page becomes an individual source entry."""
    from agents.web_agent import crawl_site
    judge_hint = f"，意图：{intent}" if intent else ""
    await append_task_log(task_id, f"🌐 整站爬取开始：{url}，最多 {max_pages} 页，深度 {max_depth}{judge_hint}")

    async def _log(msg: str):
        await append_task_log(task_id, msg)

    try:
        docs = await crawl_site(
            url,
            max_pages=max_pages,
            max_depth=max_depth,
            mode=mode,
            log_cb=_log,
            cookies=cookies,
            intent=intent,
        )
    except Exception as exc:
        await append_task_log(task_id, f"❌ 整站爬取异常：{exc}")
        await update_task(task_id, "error", error=str(exc))
        await update_source_status(source_id, "error")
        return

    if not docs:
        await update_task(task_id, "done")
        await update_source_status(source_id, "done")
        return

    for doc in docs:
        page_url = doc.metadata.get("source_url", url)
        page_src_id = str(uuid.uuid4())
        page_task_id = str(uuid.uuid4())
        page_extra = {
            **extra,
            "source_name": page_url,
            "source_url": page_url,
            "parent_site": url,
        }
        await insert_source({
            "id": page_src_id,
            "name": page_url,
            "type": "url",
            "url": page_url,
            "tags": extra.get("tags", []),
        })
        await insert_task({"id": page_task_id, "source_id": page_src_id, "status": "pending"})
        try:
            await run_ingest_pipeline(page_src_id, page_task_id, doc, extra_metadata=page_extra)
        except Exception as _page_err:
            import logging as _lg
            _lg.getLogger(__name__).warning("page ingest failed for %s: %s", page_url, _page_err)

    # Mark the parent "site" source as done
    await update_task(task_id, "done")
    await update_source_status(source_id, "done")


# ── Endpoints ─────────────────────────────────────────────────

@router.post("/file")
async def ingest_file(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    tags: str = Form(default=""),
):
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    results = []

    for upload in files:
        source_id = str(uuid.uuid4())
        task_id = str(uuid.uuid4())
        filename = upload.filename or "unknown"
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"

        content = await upload.read()
        saved_path = await save_file(source_id, filename, content)

        await insert_source(
            {"id": source_id, "name": filename, "type": ext, "url": None, "tags": tag_list}
        )
        await insert_task({"id": task_id, "source_id": source_id, "status": "pending"})

        background_tasks.add_task(
            _run_file_task,
            source_id, task_id, str(saved_path), ext,
            {"source_name": filename, "tags": tag_list},
        )
        results.append({"source_id": source_id, "task_id": task_id, "filename": filename})

    return {"results": results}


@router.post("/text")
async def ingest_text(req: TextIngestRequest, background_tasks: BackgroundTasks):
    source_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())

    await insert_source(
        {"id": source_id, "name": req.title, "type": "text", "url": None, "tags": req.tags}
    )
    await insert_task({"id": task_id, "source_id": source_id, "status": "pending"})

    background_tasks.add_task(
        _run_text_task,
        source_id, task_id, req.content,
        {"source_name": req.title, "tags": req.tags},
    )
    return {"source_id": source_id, "task_id": task_id}


@router.post("/url")
async def ingest_url(req: UrlIngestRequest, background_tasks: BackgroundTasks):
    source_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    title = req.title or req.url

    await insert_source(
        {"id": source_id, "name": title, "type": "url", "url": req.url, "tags": req.tags}
    )
    await insert_task({"id": task_id, "source_id": source_id, "status": "pending"})

    background_tasks.add_task(
        _run_url_task,
        source_id, task_id, req.url,
        {"source_name": title, "source_url": req.url, "tags": req.tags},
        req.mode,
        req.cookies,
        req.intent or ", ".join(req.tags),
    )
    return {"source_id": source_id, "task_id": task_id}


@router.post("/site")
async def ingest_site(req: SiteIngestRequest, background_tasks: BackgroundTasks):
    """Start a BFS site crawl. Each page becomes a separate source entry."""
    source_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    title = req.title or f"Site: {req.url}"

    await insert_source(
        {"id": source_id, "name": title, "type": "site", "url": req.url, "tags": req.tags}
    )
    await insert_task({"id": task_id, "source_id": source_id, "status": "pending"})

    background_tasks.add_task(
        _run_site_task,
        source_id, task_id, req.url,
        req.max_pages, req.max_depth, req.mode,
        {"source_name": title, "source_url": req.url, "tags": req.tags},
        req.cookies,
        req.intent or ", ".join(req.tags),
    )
    return {
        "source_id": source_id,
        "task_id": task_id,
        "message": f"整站爬取已开始，最多 {req.max_pages} 页，深度 {req.max_depth}",
    }


@router.get("/tasks")
async def get_tasks(limit: int = 50, offset: int = 0):
    return await list_tasks(limit=limit, offset=offset)


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
