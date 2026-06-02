from __future__ import annotations
import uuid
from typing import Any

from agents.doc_agent import RawDocument
from pipeline.extractor import extract_metadata
from storage.metadata_db import append_task_log, update_source_status, update_task


async def run_ingest_pipeline(
    source_id: str,
    task_id: str,
    raw_doc: RawDocument,
    extra_metadata: dict[str, Any] | None = None,
) -> int:
    """Wiki-first ingest: extract text → generate wiki pages. Returns wiki page count."""
    await update_task(task_id, "processing")
    await update_source_status(source_id, "processing")
    await append_task_log(task_id, "📥 开始知识提取")

    try:
        await append_task_log(task_id, "📄 解析元数据")
        meta = extract_metadata(
            raw_doc.content,
            raw_doc.metadata.get("file_type", "unknown"),
            url=raw_doc.metadata.get("source_url"),
        )
        if extra_metadata:
            meta.update(extra_metadata)

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
                    await append_task_log(task_id, f"🏷️ 自动标签: {', '.join(auto_tags)}")
                    from storage.metadata_db import update_source_tags
                    await update_source_tags(source_id, list(auto_tags))
            except Exception:
                pass

        title = meta.get("title") or raw_doc.metadata.get("title") or source_id
        await append_task_log(task_id, "🧠 Wiki 生成: LLM 分析与页面创建中…")
        try:
            from utils.agent_bus import emit
            emit(f"📥 摄入: {title[:60]}", kind="progress", agent="ingest", task_id=task_id)
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
            await append_task_log(task_id, f"⚠️ Wiki 分析失败: {result.error}")
            try:
                from utils.agent_bus import emit
                emit(f"⚠️ Wiki 失败: {result.error[:80]}", kind="error", agent="ingest", task_id=task_id)
            except Exception:
                pass
        elif total == 0:
            await append_task_log(task_id, "⚠️ Wiki 未生成新页面（可能内容过短或无实体）")
        else:
            await append_task_log(task_id, f"✅ Wiki: {result.pages_created} 新页面 / {result.pages_updated} 更新 / {result.edges_added} 边")
            try:
                from utils.agent_bus import emit
                emit(f"✅ Wiki: {result.pages_created} 新页面 / {result.pages_updated} 更新", kind="success", agent="ingest", task_id=task_id)
            except Exception:
                pass

        await update_task(task_id, "done")
        await update_source_status(source_id, "done")
        return total

    except Exception as exc:
        await append_task_log(task_id, f"❌ 错误：{exc}")
        await update_task(task_id, "error", error=str(exc))
        await update_source_status(source_id, "error")
        raise
