from __future__ import annotations
import asyncio
import json
import re
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import settings
from pipeline.embedder import embed_dense, embed_sparse
from storage.vector_store import hybrid_search

# Pattern for inline citation markers like ``[1]`` or ``[1, 3]`` that the LLM
# emits per the RAG system prompt. We only count digits 1-99 to avoid matching
# arbitrary bracketed text (footnotes, regex literals, etc.).
_CITATION_RE = re.compile(r"\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]")
# How many of the most recent user turns to merge into the retrieval query.
# Pure last-message retrieval breaks on follow-up questions like "它的优势是什么？"
_RETRIEVAL_HISTORY_TURNS = 3

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


async def _retrieve(query: str, top_k: int, filters: dict | None, qdrant_filter: object = None) -> list[dict]:
    from pipeline.retrieval import retrieve_chunks

    retrieval = await retrieve_chunks(
        query=query,
        top_k=top_k,
        filters=filters,
        mode="hybrid",
        rerank=True,
        diversify=True,
        expand=True,
        qdrant_filter=qdrant_filter,
    )
    return retrieval.results


def _build_context(chunks: list[dict]) -> str:
    parts = []
    for i, c in enumerate(chunks, 1):
        src = c["metadata"].get("source_name") or c["metadata"].get("source_url", "unknown")
        parts.append(f"[{i}] Source: {src}\n{c['content']}")
    return "\n\n---\n\n".join(parts)


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


def _build_retrieval_query(messages: list[Message], turns: int = _RETRIEVAL_HISTORY_TURNS) -> tuple[str, str]:
    """Construct the retrieval query and the latest user question.

    The latest user message is what the LLM ultimately answers, but using only
    that for retrieval breaks pronoun references in follow-up turns. We
    therefore concatenate the last ``turns`` user messages — older turns first,
    most recent last — so dense + sparse embeddings see the broader topic
    while still being dominated by the freshest phrasing.
    """
    user_msgs = [m.content for m in messages if m.role == "user" and m.content]
    if not user_msgs:
        return "", ""
    latest = user_msgs[-1]
    if len(user_msgs) == 1 or turns <= 1:
        return latest, latest
    history = user_msgs[-turns:]
    # Latest message repeated at the end strengthens its weight in BM25 and
    # caps a useful context boundary for the dense embedding model.
    merged = "\n".join(history) + "\n" + latest
    return merged, latest


_AGENTIC_SYSTEM_SUFFIX = """\

## Agent tools

You may call any of the following tools to ground your answer:

* `search_kb(query, top_k=5)` — hybrid (dense + sparse) search of the user's KB.
  Returns numbered chunks. Cite each chunk you use as `[n]` in your final
  answer using the same numbers the tool returned.
* `list_sources(tag="", limit=20)` — list ingested documents.
* `list_tags()` — list every tag in the KB.
* `get_source_chunks(source_id, limit=5)` — read a known source verbatim.
* `fetch_url_preview(url, intent="")` — fetch a fresh URL (≤ 30 s, no auth).

Workflow:
1. If the question can plausibly be answered from the KB, call `search_kb`
   first with a focused query. Use multiple targeted searches over one
   broad search when the question has sub-parts.
2. If retrieval results are thin, try `list_sources` + `get_source_chunks`
   or a tighter `search_kb(query=..., top_k=...)` call.
3. Use `fetch_url_preview` only when the user explicitly references a URL
   not in the KB or asks for live/current information.
4. Once you have enough, stop calling tools and write the final answer.
   Cite KB excerpts inline as `[1]`, `[2]`, etc. — these numbers come
   straight from the tool outputs. Never invent citations.

Be terse. Do not narrate your tool plan in the final answer."""


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

    _retrieval_query, user_query = _build_retrieval_query(req.messages)
    ctx = ChatContext(kb_filter=req.kb_filter, qdrant_filter=qdrant_filter)
    tools = build_chat_tools(ctx)
    tool_map = {t.name: t for t in tools}

    sys_prompt = system_prompt or get_rag_system_prompt()
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
                                  qdrant_filter=qdrant_filter):
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
                # If the model already produced content in the non-stream call,
                # emit it as a single chunk; otherwise stream a fresh response.
                if resp.content:
                    final_text = str(resp.content)
                    yield f"data: {json.dumps({'type': 'token', 'content': final_text})}\n\n"
                else:
                    stream_llm = _get_llm(_provider, _model, base_url=_base_url, api_key=_api_key)
                    async for chunk in stream_llm.astream(lc_msgs[:-1]):
                        tok = getattr(chunk, "content", "") or ""
                        if tok:
                            final_text += tok
                            yield f"data: {json.dumps({'type': 'token', 'content': tok})}\n\n"
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
                                  qdrant_filter=qdrant_filter):
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
            "chunk_id": c["id"],
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
) -> AsyncGenerator[str, None]:
    import logging as _lg
    from storage.metadata_db import upsert_session

    _provider = provider or req.provider or settings.llm_provider
    _model = model or req.model or settings.llm_model
    _base_url = base_url or settings.llm_base_url
    _api_key = api_key or settings.llm_api_key
    thread_id = req.thread_id or str(uuid.uuid4())

    retrieval_query, user_query = _build_retrieval_query(req.messages)

    # Single-pass retrieval — generous top_k, LLM filters via citations
    chunks = await _retrieve(retrieval_query, max(req.top_k, 10), req.kb_filter, qdrant_filter=qdrant_filter)

    llm = _get_llm(_provider, _model, base_url=_base_url, api_key=_api_key)

    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    lc_msgs = [SystemMessage(content=system_prompt or get_rag_system_prompt())]
    for msg in req.messages[:-1]:
        if msg.role == "user":
            lc_msgs.append(HumanMessage(content=msg.content))
        elif msg.role == "assistant":
            lc_msgs.append(AIMessage(content=msg.content))

    if chunks:
        ctx_str = _build_context(chunks)
        final_user = _CTX_TEMPLATE.format(chunks=ctx_str, question=user_query)
    else:
        final_user = _NO_CTX_TEMPLATE.format(question=user_query)
    lc_msgs.append(HumanMessage(content=final_user))

    full_text = ""
    async for chunk in llm.astream(lc_msgs):
        token = chunk.content
        if token:
            full_text += token
            yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

    # Real attribution: keep only the chunks the LLM actually cited via [n]
    # markers in its output. This avoids the previous behaviour of always
    # returning the entire candidate list — which made the UI's citation chain
    # show retrieved-but-unused sources as if they were answers.
    referenced_indices: set[int] = set()
    for m in _CITATION_RE.finditer(full_text):
        for raw in m.group(1).split(","):
            try:
                referenced_indices.add(int(raw.strip()))
            except ValueError:
                pass

    if referenced_indices and chunks:
        cited_chunks = [
            (i, c) for i, c in enumerate(chunks, 1)
            if i in referenced_indices
        ]
    else:
        # Fallback: LLM didn't emit any citation markers — return the full
        # candidate set so the user still sees "what was retrieved", but tag
        # them as ``unverified`` so the UI can render them differently.
        cited_chunks = [(i, c) for i, c in enumerate(chunks, 1)]

    citations = [
        {
            "index": idx,
            "chunk_id": c["id"],
            "content": c["content"][:300],
            "source": c["metadata"].get("source_name") or c["metadata"].get("source_url", ""),
            "score": round(c.get("rerank_score", c.get("score", 0)), 4),
            "verified": idx in referenced_indices,
        }
        for idx, c in cited_chunks
    ]
    yield f"data: {json.dumps({'type': 'citations', 'citations': citations})}\n\n"

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
            key = settings.llm_api_key or "none"
        else:
            return {"models": [], "default": settings.llm_model}

        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(
                f"{base}/models",
                headers={"Authorization": f"Bearer {key}"},
            )
            resp.raise_for_status()
            data = resp.json()

        models = [m["id"] for m in data.get("data", [])]
        models.sort()
        return {"models": models, "default": settings.llm_model}
    except Exception:
        # 拉取失败时返回 .env 里配置的默认模型
        return {"models": [], "default": settings.llm_model}
