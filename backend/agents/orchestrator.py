from __future__ import annotations
import uuid
from typing import Any

from agents.doc_agent import RawDocument
from pipeline.chunker import chunk_text
from pipeline.deduper import filter_duplicates
from pipeline.embedder import embed_dense, embed_sparse
from pipeline.extractor import extract_metadata
from storage.metadata_db import append_task_log, insert_chunks, update_source_status, update_task
from storage.vector_store import ChunkDoc, upsert_chunks


async def run_ingest_pipeline(
    source_id: str,
    task_id: str,
    raw_doc: RawDocument,
    extra_metadata: dict[str, Any] | None = None,
) -> int:
    """Full ingest pipeline: chunk → embed → store. Returns stored chunk count."""
    await update_task(task_id, "processing")
    await update_source_status(source_id, "processing")
    await append_task_log(task_id, "⚙️ 开始摄入流程")

    try:
        await append_task_log(task_id, "📄 提取元数据")
        meta = extract_metadata(
            raw_doc.content,
            raw_doc.metadata.get("file_type", "unknown"),
            url=raw_doc.metadata.get("source_url"),
        )
        meta.update(raw_doc.metadata)
        if extra_metadata:
            meta.update(extra_metadata)
        meta["source_id"] = source_id

        # Auto-tag: call LLM to extract tags when none were provided
        from config import settings
        if settings.autotag_enabled and not meta.get("tags"):
            try:
                await append_task_log(task_id, "🏷️ 自动标签中…")
                from pipeline.tagger import auto_tag
                from storage.metadata_db import update_source_tags
                tags = await auto_tag(raw_doc.content)
                if tags:
                    meta["tags"] = tags
                    await update_source_tags(source_id, tags)
                    await append_task_log(task_id, f"🏷️ 标签：{', '.join(tags)}")
            except Exception:
                pass  # tagging failure must never abort ingest

        await append_task_log(task_id, "✂️ 分块中…")
        text_chunks = chunk_text(raw_doc.content, source_id=source_id, base_metadata=meta)
        if not text_chunks:
            await append_task_log(task_id, "⚠️ 无有效文本片段，已跳过")
            await update_task(task_id, "done")
            await update_source_status(source_id, "done")
            return 0

        await append_task_log(task_id, f"✂️ 分块完成，共 {len(text_chunks)} 个片段")

        chunk_dicts = [
            {
                "id": str(uuid.uuid4()),
                "source_id": source_id,
                "content": c.content,
                "chunk_index": c.chunk_index,
                "metadata": c.metadata,
            }
            for c in text_chunks
        ]

        await append_task_log(task_id, "🔍 去重检查…")
        unique = await filter_duplicates(chunk_dicts)
        if not unique:
            await append_task_log(task_id, "⚠️ 所有片段均重复，已跳过")
            await update_task(task_id, "done")
            await update_source_status(source_id, "done")
            return 0
        await append_task_log(task_id, f"🔍 去重后 {len(unique)} 个片段")

        texts = [c["content"] for c in unique]
        await append_task_log(task_id, f"🧠 向量化 {len(texts)} 个片段…")
        dense_vecs = await embed_dense(texts)
        sparse_vecs = embed_sparse(texts)
        await append_task_log(task_id, "🧠 向量化完成")

        chunk_docs = [
            ChunkDoc(
                id=c["id"],
                content=c["content"],
                dense_vector=dv,
                sparse_indices=sv[0],
                sparse_values=sv[1],
                metadata=c["metadata"],
            )
            for c, dv, sv in zip(unique, dense_vecs, sparse_vecs)
        ]

        await upsert_chunks(chunk_docs)
        await insert_chunks(unique)

        await append_task_log(task_id, f"✅ 摄入完成，存储 {len(unique)} 个片段")
        await update_task(task_id, "done")
        await update_source_status(source_id, "done")
        return len(unique)

    except Exception as exc:
        await append_task_log(task_id, f"❌ 错误：{exc}")
        await update_task(task_id, "error", error=str(exc))
        await update_source_status(source_id, "error")
        raise
