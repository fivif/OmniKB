from __future__ import annotations
import asyncio
import logging
import os
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
    list_resumable_tasks,
    list_tasks,
    update_source_status,
    update_task,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class TextIngestRequest(BaseModel):
    content: str
    title: str = "Untitled"
    tags: list[str] = []


class UrlIngestRequest(BaseModel):
    url: str
    title: str | None = None
    tags: list[str] = []
    cookies: dict[str, str] | None = None  # {name: value} for authenticated pages
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
    cookies: dict | None = None,
    intent: str = "",
) -> None:
    await append_task_log(task_id, f"🌐 智能抓取：{url}{'  意图：' + intent if intent else ''}")
    from agents.web.loop import run_agent
    try:
        raw_doc = await run_agent(url=url, intent=intent, task_id=task_id)
    except Exception as exc:
        await append_task_log(task_id, f"❌ 智能抓取失败：{exc}")
        await update_task(task_id, "error", error=str(exc))
        await update_source_status(source_id, "error")
        return
    # Apply quality gates (web_judge) to agent output
    try:
        from agents.web_agent import _apply_quality_gates
        raw_doc = await _apply_quality_gates(raw_doc, url, intent)
    except ValueError as exc:
        await append_task_log(task_id, f"🚫 Agent 输出被 LLM 判定无价值，已跳过：{exc}")
        await update_task(task_id, "done")
        await update_source_status(source_id, "done")
        return
    await run_ingest_pipeline(source_id, task_id, raw_doc, extra_metadata=extra)


# `_run_site_task` schedules per-page ingest via `insert_task` directly inside
# the crawler. Those follow-up tasks share the same site-level URL params, so
# they are also resumable as long as we record the source_url on the task row.

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
        await insert_task({
            "id": task_id, "source_id": source_id, "status": "pending",
            "params": {
                "kind": "file",
                "file_path": str(saved_path),
                "file_type": ext,
                "extra": {"source_name": filename, "tags": tag_list},
            },
        })

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
    await insert_task({
        "id": task_id, "source_id": source_id, "status": "pending",
        "params": {
            "kind": "text",
            "content": req.content,
            "extra": {"source_name": req.title, "tags": req.tags},
        },
    })

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
    await insert_task({
        "id": task_id, "source_id": source_id, "status": "pending",
        "params": {
            "kind": "url",
            "url": req.url,
            "extra": {"source_name": title, "source_url": req.url, "tags": req.tags},
            "cookies": req.cookies,
            "intent": req.intent or ", ".join(req.tags),
        },
    })

    background_tasks.add_task(
        _run_url_task,
        source_id, task_id, req.url,
        {"source_name": title, "source_url": req.url, "tags": req.tags},
        req.cookies,
        req.intent or ", ".join(req.tags),
    )
    return {"source_id": source_id, "task_id": task_id}


# ── Endpoints ─────────────────────────────────────────────────
@router.get("/tasks")
async def get_tasks(limit: int = 50, offset: int = 0):
    return await list_tasks(limit=limit, offset=offset)


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


# ── Crash recovery ────────────────────────────────────────────


async def resume_pending_tasks() -> dict:
    """Re-queue tasks that were left in ``pending`` / ``processing`` state by a
    previous process crash. Called from the FastAPI lifespan startup hook.

    Strategy
    --------
    For each resumable task we read ``params_json``:

    - ``file``: re-run only when the saved file still exists on disk; otherwise
      mark the task as ``error`` so users can re-upload.
    - ``text`` / ``url``: schedule the corresponding ``_run_*_task``
      coroutine on the running event loop.
    - Older tasks without recorded ``params`` cannot be safely re-run; we mark
      them as ``error`` with a descriptive message so they stop showing as
      "processing" forever.
    """
    rows = await list_resumable_tasks()
    resumed = 0
    failed = 0
    skipped = 0

    for t in rows:
        task_id = t["id"]
        source_id = t["source_id"]
        params = t.get("params") or {}
        kind = params.get("kind")

        if not kind:
            await append_task_log(task_id, "🧯 启动检测：缺少重放参数，标记为 error")
            await update_task(task_id, "error", error="missing params after restart")
            await update_source_status(source_id, "error")
            failed += 1
            continue

        try:
            if kind == "file":
                fp = params.get("file_path")
                if not fp or not os.path.exists(fp):
                    await append_task_log(task_id, f"🧯 启动检测：源文件不存在，标记为 error ({fp})")
                    await update_task(task_id, "error", error="source file missing after restart")
                    await update_source_status(source_id, "error")
                    failed += 1
                    continue
                await append_task_log(task_id, "🔁 启动重放：file")
                asyncio.create_task(_run_file_task(
                    source_id, task_id, fp,
                    params.get("file_type", "txt"),
                    params.get("extra") or {},
                ))
            elif kind == "text":
                content = params.get("content") or ""
                if not content:
                    await append_task_log(task_id, "🧯 启动检测：文本为空，标记为 error")
                    await update_task(task_id, "error", error="empty text after restart")
                    await update_source_status(source_id, "error")
                    failed += 1
                    continue
                await append_task_log(task_id, "🔁 启动重放：text")
                asyncio.create_task(_run_text_task(
                    source_id, task_id, content, params.get("extra") or {},
                ))
            elif kind == "url":
                await append_task_log(task_id, "🔁 启动重放：url")
                asyncio.create_task(_run_url_task(
                    source_id, task_id, params.get("url", ""),
                    params.get("extra") or {},
                    params.get("cookies"),
                    params.get("intent") or "",
                ))
            else:
                await append_task_log(task_id, f"🧯 启动检测：未知 kind={kind}，标记为 error")
                await update_task(task_id, "error", error=f"unknown task kind: {kind}")
                await update_source_status(source_id, "error")
                failed += 1
                continue
            resumed += 1
        except Exception as exc:
            logger.warning("resume task %s failed: %s", task_id, exc)
            await update_task(task_id, "error", error=f"resume failed: {exc}")
            await update_source_status(source_id, "error")
            failed += 1

    if resumed or failed:
        logger.info("Task recovery: resumed=%d failed=%d skipped=%d", resumed, failed, skipped)
    return {"resumed": resumed, "failed": failed, "skipped": skipped}
