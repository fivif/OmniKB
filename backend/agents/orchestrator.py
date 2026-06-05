from __future__ import annotations
import uuid
from typing import Any
import asyncio
from agent_core.events import AgentEvent, get_event_stream

from agents.doc_agent import RawDocument
from pipeline.extractor import extract_metadata
from storage.metadata_db import append_task_log, update_source_status, update_task


def _publish_ingest_event(event_type: str, task_id: str, data: dict | None = None) -> None:
    """Publish a v2 ingest event non-blockingly. Fails silently."""
    try:
        stream = get_event_stream()
        evt = AgentEvent(type=event_type, task_id=task_id, data=data or {})
        asyncio.ensure_future(stream.publish(evt))
    except Exception:
        pass


async def run_ingest_pipeline(
    source_id: str,
    task_id: str,
    raw_doc: RawDocument,
    extra_metadata: dict[str, Any] | None = None,
) -> int:
    """Wiki-first ingest: extract text → generate wiki pages. Returns wiki page count."""
    await update_task(task_id, "processing")
    await update_source_status(source_id, "processing")
    await append_task_log(task_id, "[INGEST] 开始知识提取")
    _publish_ingest_event("ingest_start", task_id, {
        "source_id": source_id,
        "title": extra_metadata.get("source_name", source_id) if extra_metadata else source_id,
        "source_type": raw_doc.metadata.get("file_type", "unknown"),
    })

    try:
        await append_task_log(task_id, "[META] 解析元数据")
        meta = extract_metadata(
            raw_doc.content,
            raw_doc.metadata.get("file_type", "unknown"),
            url=raw_doc.metadata.get("source_url"),
        )
        if extra_metadata:
            meta.update(extra_metadata)
        _publish_ingest_event("ingest_progress", task_id, {
            "source_id": source_id,
            "stage": "metadata",
            "detail": f"Extracted, {len(raw_doc.content)} chars",
        })

        # Auto-tag: only when no tags were manually assigned
        from config import settings
        tags = meta.get("tags") or []
        if settings.autotag_enabled and (not tags or (isinstance(tags, list) and len(tags) == 0)):
            try:
                from pipeline.tagger import run_auto_tag
                title = meta.get("title") or raw_doc.metadata.get("title") or raw_doc.metadata.get("source_url") or source_id
                auto_tags = await run_auto_tag(raw_doc.content[:3000], title)
                if auto_tags:
                    meta["tags"] = list(auto_tags)
                    await append_task_log(task_id, f"[TAG] 自动标签: {', '.join(auto_tags)}")
                    from storage.metadata_db import update_source_tags
                    await update_source_tags(source_id, list(auto_tags))
            except Exception:
                pass
        _publish_ingest_event("ingest_progress", task_id, {
            "source_id": source_id,
            "stage": "autotag",
            "detail": f"Tags: {', '.join(meta.get('tags', []))}" if meta.get("tags") else "No tags",
        })

        title = meta.get("title") or raw_doc.metadata.get("title") or source_id
        await append_task_log(task_id, "[WIKI] Wiki 生成: LLM 分析与页面创建中…")
        _publish_ingest_event("ingest_progress", task_id, {
            "source_id": source_id,
            "stage": "wiki",
            "detail": "LLM analysis + page generation",
        })
        try:
            from utils.agent_bus import emit
            emit(f"[INGEST] 摄入: {title[:60]}", kind="progress", agent="ingest", task_id=task_id)
        except Exception:
            pass
        from wiki.generator import WikiGenerator
        gen = WikiGenerator(
            settings.data_dir,
            source_truncate_chars=settings.wiki_max_source_chars,
            generation_concurrency=settings.wiki_generation_concurrency,
        )
        result = await gen.generate(
            source_id=source_id,
            source_text=raw_doc.content,
            source_metadata=dict(meta),
            task_id=task_id,
        )

        total = result.pages_created + result.pages_updated
        if result.error:
            await append_task_log(task_id, f"[WARN] Wiki 分析失败: {result.error}")
            try:
                from utils.agent_bus import emit
                emit(f"[WARN] Wiki 失败: {result.error[:80]}", kind="error", agent="ingest", task_id=task_id)
            except Exception:
                pass
        elif total == 0:
            await append_task_log(task_id, "[WARN] Wiki 未生成新页面（可能内容过短或无实体）")
        else:
            await append_task_log(task_id, f"[OK] Wiki: {result.pages_created} 新页面 / {result.pages_updated} 更新 / {result.edges_added} 边")
            try:
                from utils.agent_bus import emit
                emit(f"[OK] Wiki: {result.pages_created} 新页面 / {result.pages_updated} 更新", kind="success", agent="ingest", task_id=task_id)
            except Exception:
                pass

        _publish_ingest_event("ingest_complete", task_id, {
            "source_id": source_id,
            "title": title,
            "wiki_pages": total,
            "pages_created": result.pages_created,
            "pages_updated": result.pages_updated,
            "edges_added": result.edges_added,
        })
        await update_task(task_id, "done")
        await update_source_status(source_id, "done")
        return total

    except Exception as exc:
        await append_task_log(task_id, f"[ERR] 错误：{exc}")
        _publish_ingest_event("ingest_error", task_id, {
            "source_id": source_id,
            "title": extra_metadata.get("source_name", source_id) if extra_metadata else source_id,
            "error": str(exc),
        })
        await update_task(task_id, "error", error=str(exc))
        await update_source_status(source_id, "error")
        raise
