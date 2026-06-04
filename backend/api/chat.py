from __future__ import annotations
import json
import re
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import settings

# Pattern for inline citation markers like ``[1]`` or ``[1, 3]`` that the LLM
# emits per the RAG system prompt. We only count digits 1-99 to avoid matching
# arbitrary bracketed text (footnotes, regex literals, etc.).
_CITATION_RE = re.compile(r"\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]")

router = APIRouter()

# Runtime-overridable RAG system prompt. Initialised from config on first import;
# callers can update ``_rag_system_prompt`` directly (e.g. from the settings API).
_rag_system_prompt: str | None = None


def get_rag_system_prompt() -> str:
    global _rag_system_prompt
    if _rag_system_prompt is None:
        _rag_system_prompt = settings.rag_system_prompt
    return _rag_system_prompt


def set_rag_system_prompt(prompt: str) -> None:
    global _rag_system_prompt
    _rag_system_prompt = prompt

_CTX_TEMPLATE = """\
The following excerpts from the user's personal knowledge base may be relevant. \
Use them as supplementary reference alongside your own knowledge.

<context>
{chunks}
</context>

User question: {question}"""

_NO_CTX_TEMPLATE = "{question}"



class Message(BaseModel):
    role: str  # user | assistant | system
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]
    kb_filter: dict[str, str] | None = None
    provider: str | None = None
    model: str | None = None
    top_k: int = 5
    thread_id: str | None = None  # persistent session ID
    agentic: bool | None = None
    """Override the agentic-chat global flag for this request.

    * ``True``  — force the agentic loop (KB tools, fetch_url_preview, etc.)
    * ``False`` — force the legacy single-shot RAG path
    * ``None``  — respect ``settings.chat_agent_enabled``
    """


def _get_llm(provider: str, model: str, *, base_url: str | None = None, api_key: str | None = None):
    from agents.llm import build_chat_model, normalize_provider

    _base_url = base_url or settings.llm_base_url
    _api_key = api_key or settings.llm_api_key
    normalized = normalize_provider(provider, model=model, base_url=_base_url)
    return build_chat_model(
        normalized,
        model,
        api_key=_api_key,
        base_url=_base_url,
        streaming=True,
    )


def _get_last_user_message(messages: list[Message]) -> str:
    """Return the last user message content, or empty string if none."""
    for m in reversed(messages):
        if m.role == "user" and m.content:
            return m.content
    return ""


_AGENTIC_SYSTEM_SUFFIX = """
## Your Role
You are the OmniKB Wiki Maintainer. You read, write, and organize the knowledge base wiki.
Your job is to help the user manage their wiki — create pages, update content, find gaps,
and maintain the knowledge graph.

## Wiki Tools
* `read_wiki_page(page_id)` — fetch the full content of any wiki page
* `update_wiki_page(page_id, content)` — update an existing page's body
* `create_wiki_page(page_type, slug, title, content)` — create a new page
* `list_wiki_pages_tool(page_type?)` — list all pages, optionally filter by type
* `search_wiki_tool(query)` — search wiki pages by text query
* `get_wiki_stats_tool()` — get page counts by type and edge counts
* `fetch_url_preview(url)` — fetch external URL preview

## Rules
1. The wiki is your authoritative source — answer based on it, never fabricate
2. If the wiki lacks information, honestly say so
3. When creating pages, use appropriate page types (entity/concept/source/query)
4. When updating, preserve correct existing content and add new information
5. Maintain [[wikilinks]] between related pages in your content
6. You have a 1M token context window — read as many pages as needed
"""


def _build_agentic_llm(provider: str, model: str, *, base_url: str | None = None, api_key: str | None = None):
    """Plain (non-streaming) LLM client used for tool-calling turns."""
    from agents.llm import build_chat_model, normalize_provider

    _base_url = base_url or settings.llm_base_url
    _api_key = api_key or settings.llm_api_key
    normalized = normalize_provider(provider, model=model, base_url=_base_url)
    return build_chat_model(
        normalized,
        model,
        api_key=_api_key,
        base_url=_base_url,
    )


async def _stream_agentic(
    req: ChatRequest,
    *,
    system_prompt: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    qdrant_filter: object = None,
        wiki_source_ids: list[str] | None = None,
) -> AsyncGenerator[str, None]:
    """Agentic chat path: LLM may call KB / web tools mid-conversation.

    Streams tokens to the SSE channel the same way :func:`_stream` does,
    plus extra event types: ``tool_call``, ``tool_result``. Falls back to
    the legacy ``_stream`` path on any unhandled exception so the user
    never sees a broken chat.
    """
    import logging as _lg
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
    from storage.metadata_db import upsert_session

    from .chat_tools import ChatContext, build_chat_tools

    _provider = provider or req.provider or settings.llm_provider
    _model = model or req.model or settings.llm_model
    _base_url = base_url or settings.llm_base_url
    _api_key = api_key or settings.llm_api_key
    thread_id = req.thread_id or str(uuid.uuid4())

    user_query = _get_last_user_message(req.messages)
    ctx = ChatContext(kb_filter=req.kb_filter, qdrant_filter=qdrant_filter)
    tools = build_chat_tools(ctx)
    tool_map = {t.name: t for t in tools}

    sys_prompt = system_prompt or get_rag_system_prompt()

    # ── Wiki index disclosure (Karpathy progressive disclosure pattern) ──
    if getattr(settings, "wiki_retrieval_enabled", False):  # wiki always on, RAG removed
        try:
            from wiki.retriever import load_wiki_index
            wiki_index = await load_wiki_index(
                source_ids=wiki_source_ids,
            )
            if wiki_index:
                sys_prompt = (
                    f"<wiki_index>\n{wiki_index}\n</wiki_index>\n\n"
                    f"Use read_wiki_page(id) to fetch any page's full content.\n\n"
                    + sys_prompt
                )
        except Exception:
            pass  # wiki is best-effort, never break chat

    # Inject wiki stats
    try:
        from storage.metadata_db import count_wiki_pages_by_type, count_wikilinks
        stats = await count_wiki_pages_by_type()
        total = sum(stats.values())
        edges = await count_wikilinks()
        stats_text = f"\n\n## Wiki Stats\nTotal pages: {total} ({', '.join(f'{k}: {v}' for k,v in sorted(stats.items()))})\nTotal edges: {edges}\n"
        sys_prompt += stats_text
    except Exception:
        pass

    sys_prompt += _AGENTIC_SYSTEM_SUFFIX
    lc_msgs: list = [SystemMessage(content=sys_prompt)]
    for m in req.messages[:-1]:
        if m.role == "user":
            lc_msgs.append(HumanMessage(content=m.content))
        elif m.role == "assistant":
            lc_msgs.append(AIMessage(content=m.content))
    lc_msgs.append(HumanMessage(content=user_query))

    try:
        llm = _build_agentic_llm(_provider, _model, base_url=_base_url, api_key=_api_key)
        llm_with_tools = llm.bind_tools(tools)
    except Exception as exc:
        _lg.getLogger(__name__).warning(
            "agentic chat init failed (%s); falling back to legacy RAG", exc,
        )
        async for evt in _stream(req, system_prompt=system_prompt,
                                  provider=provider, model=model,
                                  base_url=base_url, api_key=api_key,
                                  qdrant_filter=qdrant_filter,
                                  
                                  wiki_source_ids=wiki_source_ids):
            yield evt
        return

    max_turns = max(1, getattr(settings, "chat_agent_max_turns", 6))
    max_total_tool_calls = max(1, getattr(settings, "chat_agent_max_tool_calls", 10))
    total_tool_calls = 0
    final_text = ""

    try:
        for turn in range(max_turns):
            # Non-streaming invoke when we still expect tool calls; the LLM
            # decides whether to call tools by returning ``.tool_calls``.
            resp: AIMessage = await llm_with_tools.ainvoke(lc_msgs)
            lc_msgs.append(resp)

            tool_calls = getattr(resp, "tool_calls", None) or []

            # No more tool calls — this is the final answer. Stream it
            # token-by-token by re-issuing as a streaming call against the
            # same context, so the user sees progressive output.
            if not tool_calls:
                # Always stream the final answer token-by-token
                stream_llm = _get_llm(_provider, _model, base_url=_base_url, api_key=_api_key)
                async for chunk in stream_llm.astream(lc_msgs[:-1]):
                    tok = getattr(chunk, "content", "") or ""
                    if tok:
                        final_text += tok
                        yield f"data: {json.dumps({'type': 'token', 'content': tok})}\n\n"
                # Fallback: if streaming produced nothing (empty response),
                # use the non-stream content as a single chunk
                if not final_text and resp.content:
                    final_text = str(resp.content)
                    yield f"data: {json.dumps({'type': 'token', 'content': final_text})}\n\n"
                break

            # Execute the requested tools (sequentially — most are cheap
            # DB lookups; the only network call is fetch_url_preview).
            for tc in tool_calls:
                if total_tool_calls >= max_total_tool_calls:
                    blocked_payload = json.dumps({
                        "type": "tool_result",
                        "name": tc.get("name", "?"),
                        "content": "[budget: chat tool-call cap reached]",
                    })
                    yield f"data: {blocked_payload}\n\n"
                    lc_msgs.append(ToolMessage(
                        content="[budget: chat tool-call cap reached]",
                        tool_call_id=tc.get("id", ""),
                    ))
                    continue

                name = tc.get("name", "")
                args = tc.get("args", {}) or {}
                tcid = tc.get("id", "")
                yield "data: " + json.dumps({
                    "type": "tool_call",
                    "name": name,
                    "args": args,
                }, ensure_ascii=False) + "\n\n"

                t = tool_map.get(name)
                if t is None:
                    result = f"[unknown tool: {name}]"
                else:
                    try:
                        result = await t.ainvoke(args)
                    except Exception as exc:
                        result = f"[{name} error: {exc}]"

                result_str = str(result)
                total_tool_calls += 1
                lc_msgs.append(ToolMessage(content=result_str, tool_call_id=tcid))

                preview = result_str[:400]
                yield "data: " + json.dumps({
                    "type": "tool_result",
                    "name": name,
                    "content": preview,
                    "truncated": len(result_str) > len(preview),
                }, ensure_ascii=False) + "\n\n"
        else:
            # max_turns reached without a tool-call-free response: surface
            # whatever the last assistant message said.
            final_text = str(getattr(resp, "content", "") or final_text)
            if final_text:
                yield f"data: {json.dumps({'type': 'token', 'content': final_text})}\n\n"
    except Exception as exc:
        _lg.getLogger(__name__).warning(
            "agentic chat loop failed (%s); falling back to legacy RAG", exc,
        )
        async for evt in _stream(req, system_prompt=system_prompt,
                                  provider=provider, model=model,
                                  base_url=base_url, api_key=api_key,
                                  qdrant_filter=qdrant_filter,
                                  
                                  wiki_source_ids=wiki_source_ids):
            yield evt
        return

    # ── Citations ───────────────────────────────────────────────────
    referenced_indices: set[int] = set()
    for mm in _CITATION_RE.finditer(final_text):
        for raw in mm.group(1).split(","):
            try:
                referenced_indices.add(int(raw.strip()))
            except ValueError:
                pass

    chunks = ctx.retrieved_chunks
    if referenced_indices and chunks:
        cited_chunks = [
            (i, c) for i, c in enumerate(chunks, 1) if i in referenced_indices
        ]
    else:
        cited_chunks = [(i, c) for i, c in enumerate(chunks, 1)]

    citations = [
        {
            "index": idx,
            "chunk_id": c.get("id", ""),
            "content": (c.get("content") or "")[:300],
            "source": c["metadata"].get("source_name") or c["metadata"].get("source_url", ""),
            "score": round(c.get("rerank_score", c.get("score", 0)) or 0, 4),
            "verified": idx in referenced_indices,
        }
        for idx, c in cited_chunks
    ]
    yield f"data: {json.dumps({'type': 'citations', 'citations': citations})}\n\n"

    if ctx.fetched_urls:
        yield "data: " + json.dumps(
            {"type": "fetched_urls", "urls": ctx.fetched_urls}, ensure_ascii=False,
        ) + "\n\n"

    updated_messages = [m.model_dump() for m in req.messages] + [
        {"role": "assistant", "content": final_text}
    ]
    try:
        await upsert_session(thread_id, updated_messages)
    except Exception as _sess_err:
        import logging as _lg2
        _lg2.getLogger(__name__).warning(
            "agentic session persist failed for %s: %s", thread_id, _sess_err,
        )

    yield f"data: {json.dumps({'type': 'session', 'thread_id': thread_id})}\n\n"
    yield "data: [DONE]\n\n"


async def _stream(
    req: ChatRequest,
    *,
    system_prompt: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    qdrant_filter: object = None,
    skip_session: bool = False,
        wiki_source_ids: list[str] | None = None,
) -> AsyncGenerator[str, None]:
    import logging as _lg
    from storage.metadata_db import upsert_session

    _provider = provider or req.provider or settings.llm_provider
    _model = model or req.model or settings.llm_model
    _base_url = base_url or settings.llm_base_url
    _api_key = api_key or settings.llm_api_key
    thread_id = req.thread_id or str(uuid.uuid4())

    user_query = _get_last_user_message(req.messages)

    # ── Agent console event (v1 bus) ─────────────────────────
    from utils.agent_bus import emit
    task_id = thread_id

    # ── Wiki index disclosure (Karpathy progressive disclosure pattern) ──
    wiki_context = ""
    if getattr(settings, "wiki_retrieval_enabled", False):  # wiki always on, RAG removed
        try:
            from wiki.retriever import load_wiki_index
            wiki_index = await load_wiki_index(
                source_ids=wiki_source_ids,
            )
            if wiki_index:
                wiki_context = (
                    f"<wiki_index>\n{wiki_index}\n</wiki_index>\n\n"
                    f"Use read_wiki_page(id) to fetch any page's full content."
                )
                emit(f"📝 Wiki 索引: 已公开", kind="success", agent="rag", task_id=task_id)
        except Exception:
            pass  # wiki is best-effort, never break chat

    llm = _get_llm(_provider, _model, base_url=_base_url, api_key=_api_key)

    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    lc_msgs = [SystemMessage(content=system_prompt or get_rag_system_prompt())]
    for msg in req.messages[:-1]:
        if msg.role == "user":
            lc_msgs.append(HumanMessage(content=msg.content))
        elif msg.role == "assistant":
            lc_msgs.append(AIMessage(content=msg.content))

    if wiki_context:
        final_user = _CTX_TEMPLATE.format(chunks=wiki_context, question=user_query)
    else:
        final_user = _NO_CTX_TEMPLATE.format(question=user_query)
    lc_msgs.append(HumanMessage(content=final_user))

    emit(f"💬 LLM 生成中...", kind="progress", agent="rag", task_id=task_id)
    full_text = ""
    async for chunk in llm.astream(lc_msgs):
        token = chunk.content
        if token:
            full_text += token
            yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
    emit(f"✅ 回答完成 ({len(full_text)} 字)", kind="success", agent="rag", task_id=task_id)

    # RAG removed — no chunk retrieval, citations always empty
    yield f"data: {json.dumps({'type': 'citations', 'citations': []})}\n\n"

    # Persist session to DB (skip for external/scenario API)
    if not skip_session:
        updated_messages = [m.model_dump() for m in req.messages] + [
            {"role": "assistant", "content": full_text}
        ]
        try:
            await upsert_session(thread_id, updated_messages)
        except Exception as _sess_err:
            _lg.getLogger(__name__).warning("session persist failed for %s: %s", thread_id, _sess_err)

    yield f"data: {json.dumps({'type': 'session', 'thread_id': thread_id})}\n\n"
    yield "data: [DONE]\n\n"


def _resolve_stream(req: ChatRequest):
    use_agentic = req.agentic if req.agentic is not None else getattr(
        settings, "chat_agent_enabled", True,
    )
    return _stream_agentic(req) if use_agentic else _stream(req)


@router.post("")
async def chat(req: ChatRequest):
    return StreamingResponse(
        _resolve_stream(req),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/sessions/{thread_id}")
async def delete_session(thread_id: str):
    """Clear a conversation session's stored history."""
    from storage.metadata_db import delete_session as db_delete
    await db_delete(thread_id)
    return {"status": "deleted", "thread_id": thread_id}


@router.get("/models")
async def list_models():
    """Return available models from the configured LLM provider endpoint."""
    import httpx
    from agents.llm import normalize_provider, resolve_base_url

    provider = normalize_provider(
        settings.llm_provider,
        model=settings.llm_model,
        base_url=settings.llm_base_url,
    )
    try:
        if provider in {"deepseek", "custom"}:
            base = (resolve_base_url(provider, settings.llm_base_url) or "").rstrip("/")
            key = settings.llm_api_key
        else:
            return {"models": [], "default": settings.llm_model}

        headers = {}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(
                f"{base}/models",
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        models = [m["id"] for m in data.get("data", [])]
        models.sort()
        return {"models": models, "default": settings.llm_model}
    except Exception:
        # 拉取失败时返回 .env 里配置的默认模型
        return {"models": [], "default": settings.llm_model}
