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
    import logging as _lg
    try:
        dense = (await embed_dense([query]))[0]
    except Exception as exc:
        _lg.getLogger(__name__).warning("Dense embedding failed, cannot search: %s", exc)
        return []
    try:
        sparse = embed_sparse([query])[0]
    except Exception as exc:
        _lg.getLogger(__name__).warning("Sparse embedding failed, using dense-only: %s", exc)
        sparse = ([], [])
    filters = {"source_id": filter_source} if filter_source else None
    try:
        return await hybrid_search(
            query_dense=dense,
            query_sparse_indices=sparse[0],
            query_sparse_values=sparse[1],
            top_k=top_k,
            filters=filters,
        )
    except Exception as exc:
        _lg.getLogger(__name__).warning("Hybrid search failed: %s", exc)
        return []


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
        from api.chat import get_rag_system_prompt

        resp = await llm.ainvoke([
            SystemMessage(content=get_rag_system_prompt()),
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


async def ingest_url_tool(url: str, tags: list[str] | None = None, mode: str = "smart") -> dict:
    """Fetch and ingest a URL into the knowledge base.

    Parameters
    ----------
    mode:
        ``'auto'``/``'static'`` — scrapling static fetcher (default).
        ``'dynamic'``/``'stealth'`` — Playwright-based rendering.
        ``'agent_browser'`` — agent-browser CLI (Layer 3-A, interactive/SPA pages).
        ``'jshook'`` — jshookmcp CDP browser (Layer 3-B, anti-bot/JS-heavy).
    """
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

    raw_doc = await fetch_url(url, mode=mode)
    chunks_count = await run_ingest_pipeline(
        source_id, task_id, raw_doc,
        extra_metadata={"source_name": url, "source_url": url, "tags": tag_list},
    )

    result = {"source_id": source_id, "task_id": task_id, "chunks": chunks_count, "mode": mode}
    await _log(
        "ingest_url",
        {"url": url, "mode": mode},
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


async def browser_fetch_tool(
    url: str,
    mode: str = "agent_browser",
    max_chars: int = 8000,
) -> dict:
    """Fetch a web page and return its text content without ingesting.

    Useful when you want to read a page before deciding whether to ingest it,
    or when you need real-time web content in a chat response.

    Parameters
    ----------
    mode:
        ``'agent_browser'`` — agent-browser CLI (default, handles SPAs/JS pages).
        ``'jshook'`` — jshookmcp CDP (advanced anti-bot / network interception).
        ``'stealth'`` — scrapling stealth Playwright.
        ``'static'`` / ``'auto'`` — scrapling or httpx.
    max_chars:
        Truncate content to this many characters in the returned preview.
    """
    from agents.web_agent import fetch_url

    t0 = time.time()
    doc = await fetch_url(url, mode=mode)
    content_preview = doc.content[:max_chars]
    result = {
        "url": url,
        "mode": mode,
        "char_count": len(doc.content),
        "content": content_preview,
        "truncated": len(doc.content) > max_chars,
    }
    await _log(
        "browser_fetch",
        {"url": url, "mode": mode},
        f"{len(doc.content)} chars",
        int((time.time() - t0) * 1000),
    )
    return result


async def jshook_call_tool(tool_name: str, arguments: dict) -> dict:
    """Call any jshookmcp tool directly by name.

    jshookmcp exposes 387+ tools for browser automation, CDP debugging,
    network interception, JS deobfuscation, WASM analysis, and more.

    To discover available tools use ``tool_name='search_tools'`` with
    ``arguments={'query': '<your query>'}``.

    Common tools:
    - ``search_tools`` — BM25-ranked tool discovery
    - ``browser_launch`` / ``browser_close`` — start/stop browser
    - ``page_navigate`` — navigate to URL
    - ``page_evaluate`` — run JS in page context
    - ``stealth_inject`` — inject anti-detection scripts
    - ``page_cookies`` — manage cookies
    - ``network_monitor_start`` — capture XHR/fetch requests
    """
    from agents.jshook_client import JsHookMcpClient

    t0 = time.time()
    async with JsHookMcpClient(profile="workflow") as client:
        raw = await client.call_tool(tool_name, arguments, timeout=90.0)
        text = JsHookMcpClient.extract_text(raw)

    result = {"tool": tool_name, "result": text[:4000], "raw_truncated": len(text) > 4000}
    await _log(
        "jshook_call",
        {"tool": tool_name, "args_keys": list(arguments.keys())},
        text[:200],
        int((time.time() - t0) * 1000),
    )
    return result
