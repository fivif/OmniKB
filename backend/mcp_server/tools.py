from __future__ import annotations
import json
import time
import uuid
from datetime import datetime, timezone

from pipeline.embedder import embed_dense, embed_sparse
from storage.metadata_db import (
    get_chunk as db_get_chunk,
    insert_mcp_log,
    list_sources as db_list_sources,
)
from storage.vector_store import hybrid_search


# ── Internal search helper ────────────────────────────────────

async def _do_search(
    query: str,
    top_k: int = 10,
    filter_source: str | None = None,
) -> list[dict]:
    dense = (await embed_dense([query]))[0]
    sparse = embed_sparse([query])[0]
    filters = {"source_id": filter_source} if filter_source else None
    return await hybrid_search(
        query_dense=dense,
        query_sparse_indices=sparse[0],
        query_sparse_values=sparse[1],
        top_k=top_k,
        filters=filters,
    )


# ── Call logging helper ───────────────────────────────────────

async def _log(tool_name: str, args: dict, result_preview: str, duration_ms: int) -> None:
    try:
        await insert_mcp_log({
            "id": str(uuid.uuid4()),
            "tool_name": tool_name,
            "args_json": json.dumps(args, ensure_ascii=False)[:1000],
            "result_preview": result_preview[:500] if result_preview else None,
            "duration_ms": duration_ms,
            "called_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as _log_err:
        import logging as _lg
        _lg.getLogger(__name__).debug("mcp_log insert failed: %s", _log_err)


# ── Public tools ──────────────────────────────────────────────

async def search_kb(
    query: str,
    top_k: int = 10,
    filter_source: str | None = None,
) -> list[dict]:
    t0 = time.time()
    result = await _do_search(query, top_k, filter_source)
    await _log(
        "search_kb",
        {"query": query[:200], "top_k": top_k},
        f"{len(result)} results",
        int((time.time() - t0) * 1000),
    )
    return result


async def ask_kb(question: str, context_k: int = 5) -> dict:
    """Search the KB and generate an LLM answer with citations."""
    from config import settings

    t0 = time.time()
    chunks = await _do_search(question, top_k=context_k)
    context = "\n\n".join(f"[{i + 1}] {c['content']}" for i, c in enumerate(chunks))

    answer = ""
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key or "none",
            base_url=settings.llm_base_url or None,
            temperature=0,
        )
        resp = await llm.ainvoke([
            SystemMessage(
                content=(
                    "You are a knowledge base assistant. "
                    "Answer the question using the provided context. "
                    "Cite sources as [1], [2], etc. "
                    "If the context is insufficient, say so."
                )
            ),
            HumanMessage(content=f"Context:\n{context}\n\nQuestion: {question}"),
        ])
        answer = resp.content
    except Exception as exc:
        answer = f"[LLM error: {exc}]\n\nRaw context:\n{context}"

    result = {"question": question, "answer": answer, "chunks": chunks}
    await _log(
        "ask_kb",
        {"question": question[:200], "context_k": context_k},
        answer[:300],
        int((time.time() - t0) * 1000),
    )
    return result


async def ingest_url_tool(url: str, tags: list[str] | None = None) -> dict:
    """Fetch and ingest a URL into the knowledge base."""
    import uuid as _uuid
    from agents.web_agent import fetch_url
    from agents.orchestrator import run_ingest_pipeline
    from storage.metadata_db import insert_source, insert_task

    t0 = time.time()
    source_id = str(_uuid.uuid4())
    task_id = str(_uuid.uuid4())
    tag_list = tags or []

    await insert_source({"id": source_id, "name": url, "type": "url", "url": url, "tags": tag_list})
    await insert_task({"id": task_id, "source_id": source_id, "status": "pending"})

    raw_doc = await fetch_url(url)
    chunks_count = await run_ingest_pipeline(
        source_id, task_id, raw_doc,
        extra_metadata={"source_name": url, "source_url": url, "tags": tag_list},
    )

    result = {"source_id": source_id, "task_id": task_id, "chunks": chunks_count}
    await _log(
        "ingest_url",
        {"url": url},
        f"source_id={source_id}, chunks={chunks_count}",
        int((time.time() - t0) * 1000),
    )
    return result


async def ingest_text_tool(
    text: str,
    title: str = "Untitled",
    tags: list[str] | None = None,
) -> dict:
    import uuid as _uuid
    from agents.doc_agent import parse_text
    from agents.orchestrator import run_ingest_pipeline
    from storage.metadata_db import insert_source, insert_task

    t0 = time.time()
    source_id = str(_uuid.uuid4())
    task_id = str(_uuid.uuid4())
    tag_list = tags or []

    await insert_source({"id": source_id, "name": title, "type": "text", "url": None, "tags": tag_list})
    await insert_task({"id": task_id, "source_id": source_id, "status": "pending"})

    raw_doc = parse_text(text)
    chunks_count = await run_ingest_pipeline(
        source_id, task_id, raw_doc,
        extra_metadata={"source_name": title, "tags": tag_list},
    )

    result = {"source_id": source_id, "task_id": task_id, "chunks": chunks_count}
    await _log(
        "ingest_text",
        {"title": title, "length": len(text)},
        f"source_id={source_id}, chunks={chunks_count}",
        int((time.time() - t0) * 1000),
    )
    return result


async def list_sources_tool(limit: int = 20, offset: int = 0) -> list[dict]:
    t0 = time.time()
    result = await db_list_sources(limit=limit, offset=offset)
    await _log("list_sources", {"limit": limit, "offset": offset}, f"{len(result)} sources", int((time.time() - t0) * 1000))
    return result


async def get_chunk_tool(chunk_id: str) -> dict | None:
    t0 = time.time()
    result = await db_get_chunk(chunk_id)
    await _log("get_chunk", {"chunk_id": chunk_id}, "found" if result else "not found", int((time.time() - t0) * 1000))
    return result
