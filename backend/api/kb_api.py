"""Public KB Q&A API — Bearer-token authenticated, scenario-scoped RAG chat.

External applications call ``POST /kb/{scenario_id}/chat`` with a Bearer token
(one of the scenario's API keys) to get streaming RAG responses filtered to the
scenario's selected chunks.
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from qdrant_client.models import Filter, FieldCondition, MatchAny, HasIdCondition

from config import settings
from pipeline.retrieval import retrieve_chunks
from storage.metadata_db import (
    get_scenario,
    list_scenario_sources,
    verify_scenario_key,
)

router = APIRouter()


class KbChatMessage(BaseModel):
    role: str
    content: str


class KbChatRequest(BaseModel):
    messages: list[KbChatMessage]
    top_k: int = 8
    agentic: bool = False
    """When true, the LLM may call KB tools (search_kb, list_sources, etc.)
    autonomously within the scenario scope instead of a single RAG pass."""


_RETRIEVAL_HISTORY_TURNS = 3
_SUFFICIENCY_CHECK = """\
You are evaluating whether the retrieved context is sufficient to answer a question.
Read the context and question, then respond with exactly ONE line:

SUFFICIENT
- or -
NEED_MORE: <specific query to search for the missing information>

Question: {question}

Retrieved context:
{context}
"""

_CTX_TEMPLATE = """\
Use the following excerpts from the scenario knowledge base as internal reference.
Do not say the user provided these excerpts, do not mention how many chunks were retrieved,
and do not narrate your retrieval process. Answer the question directly and cite sources as [1], [2], etc.

<context>
{chunks}
</context>

User question: {question}"""

_NO_CTX_TEMPLATE = """\
The scenario knowledge base did not yield enough evidence for this question.
Answer carefully based on the conversation so far, and clearly say what information is missing if the KB evidence is insufficient.

User question: {question}"""


_AGENTIC_SYSTEM_SUFFIX = """\

## Available tools

You may call these tools to ground your answers in the scenario knowledge base:

* `search_kb(query, top_k=5)` — hybrid search within the scenario's documents.
  Returns numbered chunks. Cite each chunk as `[n]` in your answer.
* `list_sources(tag="", limit=20)` — list scenario documents.
* `list_tags()` — list all tags in this scenario's knowledge base.
* `get_source_chunks(source_id, limit=5)` — read a known source verbatim.
* `fetch_url_preview(url, intent="")` — fetch a live URL (≤30s, no auth).

Workflow:
1. If the question can be answered from the KB, call `search_kb` with a focused query.
2. If results are thin, try `list_sources` + `get_source_chunks` or refine your query.
3. Use `fetch_url_preview` only for URLs not in the KB or live/current information.
4. Once you have enough, stop calling tools and write the final answer.
   Cite KB excerpts inline as `[1]`, `[2]`, etc. Never invent citations.

Be terse. Do not narrate your tool plan in the final answer."""


def _build_scenario_qdrant_filter(scenario_id: str, scenario_sources: list[dict]) -> object | None:
    """Build a Qdrant Filter from scenario source/chunk bindings.

    Returns None when the scenario has no bindings (empty KB scope).
    """
    whole_source_ids = sorted({
        s["source_id"] for s in scenario_sources
        if s.get("source_id") and not s.get("chunk_id")
    })
    specific_chunk_ids = sorted({
        s["chunk_id"] for s in scenario_sources
        if s.get("chunk_id")
    })

    if not whole_source_ids and not specific_chunk_ids:
        return None

    if whole_source_ids and not specific_chunk_ids:
        return Filter(must=[FieldCondition(key="source_id", match=MatchAny(any=whole_source_ids))])
    elif specific_chunk_ids and not whole_source_ids:
        return Filter(must=[HasIdCondition(has_id=specific_chunk_ids)])
    else:
        return Filter(should=[
            FieldCondition(key="source_id", match=MatchAny(any=whole_source_ids)),
            HasIdCondition(has_id=specific_chunk_ids),
        ])


def _build_context(chunks: list[dict]) -> str:
    parts = []
    for i, c in enumerate(chunks, 1):
        src = c["metadata"].get("source_name") or c["metadata"].get("source_url", "unknown")
        parts.append(f"[{i}] Source: {src}\n{c['content']}")
    return "\n\n---\n\n".join(parts)


def _build_retrieval_query(messages: list[KbChatMessage], turns: int = _RETRIEVAL_HISTORY_TURNS) -> tuple[str, str]:
    user_msgs = [m.content for m in messages if m.role == "user" and m.content]
    if not user_msgs:
        return "", ""
    latest = user_msgs[-1]
    if len(user_msgs) == 1 or turns <= 1:
        return latest, latest
    history = user_msgs[-turns:]
    merged = "\n".join(history) + "\n" + latest
    return merged, latest


def _get_llm(provider: str, model: str, base_url: str, api_key: str):
    from agents.llm import build_chat_model

    return build_chat_model(
        provider,
        model,
        api_key=api_key,
        base_url=base_url,
        streaming=True,
    )


async def _retrieve_chunks(query: str, scenario_id: str, top_k: int) -> list[dict]:
    """Retrieve chunks from vector store, filtered to scenario's allowed chunks."""
    scenario_sources = await list_scenario_sources(scenario_id)
    whole_source_ids = sorted({
        s["source_id"] for s in scenario_sources
        if s.get("source_id") and not s.get("chunk_id")
    })
    specific_chunk_ids = sorted({
        s["chunk_id"] for s in scenario_sources
        if s.get("chunk_id")
    })

    if not whole_source_ids and not specific_chunk_ids:
        return []

    filters = None
    scenario_filter = None
    if whole_source_ids and not specific_chunk_ids:
        filters = {"source_id__in": whole_source_ids}
    elif specific_chunk_ids and not whole_source_ids:
        filters = {"_point_ids": specific_chunk_ids}
    else:
        should_conditions = [
            FieldCondition(key="source_id", match=MatchAny(any=whole_source_ids)),
            HasIdCondition(has_id=specific_chunk_ids),
        ]
        scenario_filter = Filter(should=should_conditions)

    retrieval = await retrieve_chunks(
        query=query,
        top_k=top_k,
        filters=filters,
        mode="hybrid",
        rerank=True,
        diversify=False,
        expand=True,
        fetch_k=max(top_k * 6, 30),
        qdrant_filter=scenario_filter,
    )
    return retrieval.results


async def _stream_kb_chat(
    scenario_id: str,
    req: KbChatRequest,
    sc: dict,
) -> AsyncGenerator[str, None]:
    import logging as _lg

    provider = sc.get("llm_provider") or settings.llm_provider
    model = sc.get("llm_model") or settings.llm_model
    base_url = sc.get("llm_base_url") or settings.llm_base_url
    api_key = sc.get("llm_api_key") or settings.llm_api_key or "none"

    retrieval_query, user_query = _build_retrieval_query(req.messages)

    initial_k = max(req.top_k, 10)
    all_chunks = await _retrieve_chunks(retrieval_query or user_query, scenario_id, initial_k)
    seen_ids = {chunk["id"] for chunk in all_chunks}

    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    system_prompt = (sc.get("system_prompt") or (
        "You are a helpful knowledge base assistant. "
        "Use the provided context to answer the user's question accurately. "
        "Cite sources as [1], [2], etc. when using them."
    )) + "\n\n" + (
        "Treat retrieved KB excerpts as internal context, not something the user manually provided. "
        "Never say phrases like '你提供了这些片段'、'现在我有足够的信息' or narrate the retrieval process. "
        "Answer directly, keep the conversation natural, and if evidence is insufficient, plainly say what is still missing."
    )

    llm = _get_llm(provider, model, base_url, api_key)
    for _ in range(3):
        if not all_chunks:
            break
        ctx_preview = "\n\n".join(
            f"[{i + 1}] {chunk['content'][:200]}" for i, chunk in enumerate(all_chunks[:10])
        )
        check_prompt = _SUFFICIENCY_CHECK.format(question=user_query, context=ctx_preview)
        try:
            check_resp = await llm.ainvoke([HumanMessage(content=check_prompt)])
            verdict = (check_resp.content or "").strip()
        except Exception as exc:
            _lg.getLogger(__name__).warning("Scenario sufficiency check failed: %s", exc)
            break

        if verdict.upper().startswith("SUFFICIENT"):
            break

        follow_up = verdict.split(":", 1)[1].strip() if "NEED_MORE:" in verdict.upper() else verdict
        if len(follow_up) < 3:
            break

        extra = await _retrieve_chunks(follow_up, scenario_id, initial_k)
        new_chunks = [chunk for chunk in extra if chunk["id"] not in seen_ids]
        if not new_chunks:
            break
        seen_ids.update(chunk["id"] for chunk in new_chunks)
        all_chunks.extend(new_chunks)

    chunks = all_chunks[:max(req.top_k, 10)]

    lc_msgs = [SystemMessage(content=system_prompt)]
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

    citations = [
        {
            "index": i + 1,
            "chunk_id": c["id"],
            "content": c["content"][:300],
            "source": c["metadata"].get("source_name") or c["metadata"].get("source_url", ""),
            "score": round(c.get("rerank_score", c.get("score", 0)), 4),
        }
        for i, c in enumerate(chunks)
    ]
    yield f"data: {json.dumps({'type': 'citations', 'citations': citations})}\n\n"
    yield "data: [DONE]\n\n"


def _build_agentic_llm(provider: str, model: str, base_url: str, api_key: str):
    """Plain (non-streaming) LLM for tool-calling turns."""
    from agents.llm import build_chat_model

    return build_chat_model(
        provider,
        model,
        api_key=api_key,
        base_url=base_url,
    )


async def _stream_kb_agentic(
    scenario_id: str,
    req: KbChatRequest,
    sc: dict,
    scenario_sources: list[dict],
) -> AsyncGenerator[str, None]:
    """Agentic scenario chat: LLM may call KB tools scoped to the scenario."""
    import logging as _lg
    import uuid
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    from api.chat_tools import ChatContext, build_chat_tools

    provider = sc.get("llm_provider") or settings.llm_provider
    model = sc.get("llm_model") or settings.llm_model
    base_url = sc.get("llm_base_url") or settings.llm_base_url
    api_key = sc.get("llm_api_key") or settings.llm_api_key or "none"

    _, user_query = _build_retrieval_query(req.messages)

    # Build scenario-scoped context
    qdrant_filter = _build_scenario_qdrant_filter(scenario_id, scenario_sources)
    whole_source_ids = sorted({
        s["source_id"] for s in scenario_sources
        if s.get("source_id") and not s.get("chunk_id")
    })

    ctx = ChatContext(
        qdrant_filter=qdrant_filter,
        scenario_source_ids=whole_source_ids or None,
    )
    tools = build_chat_tools(ctx)
    tool_map = {t.name: t for t in tools}

    base_system_prompt = sc.get("system_prompt") or (
        "You are a helpful knowledge base assistant. "
        "Use the provided context to answer the user's question accurately. "
        "Cite sources as [1], [2], etc. when using them."
    )
    sys_prompt = base_system_prompt + _AGENTIC_SYSTEM_SUFFIX

    lc_msgs: list = [SystemMessage(content=sys_prompt)]
    for m in req.messages[:-1]:
        if m.role == "user":
            lc_msgs.append(HumanMessage(content=m.content))
        elif m.role == "assistant":
            lc_msgs.append(AIMessage(content=m.content))
    lc_msgs.append(HumanMessage(content=user_query))

    try:
        llm = _build_agentic_llm(provider, model, base_url, api_key)
        llm_with_tools = llm.bind_tools(tools)
    except Exception as exc:
        _lg.getLogger(__name__).warning(
            "scenario agentic init failed (%s); falling back to legacy RAG", exc,
        )
        async for evt in _stream_kb_chat(scenario_id, req, sc):
            yield evt
        return

    max_total_tool_calls = max(1, getattr(settings, "chat_agent_max_tool_calls", 10))
    total_tool_calls = 0
    final_text = ""

    try:
        for _ in range(max(1, getattr(settings, "chat_agent_max_turns", 6))):
            resp: AIMessage = await llm_with_tools.ainvoke(lc_msgs)
            lc_msgs.append(resp)

            tool_calls = getattr(resp, "tool_calls", None) or []

            if not tool_calls:
                if resp.content:
                    final_text = str(resp.content)
                    yield f"data: {json.dumps({'type': 'token', 'content': final_text})}\n\n"
                else:
                    stream_llm = _get_llm(provider, model, base_url, api_key)
                    async for chunk in stream_llm.astream(lc_msgs[:-1]):
                        tok = getattr(chunk, "content", "") or ""
                        if tok:
                            final_text += tok
                            yield f"data: {json.dumps({'type': 'token', 'content': tok})}\n\n"
                break

            for tc in tool_calls:
                if total_tool_calls >= max_total_tool_calls:
                    blocked = json.dumps({
                        "type": "tool_result",
                        "name": tc.get("name", "?"),
                        "content": "[budget: chat tool-call cap reached]",
                    })
                    yield f"data: {blocked}\n\n"
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

                total_tool_calls += 1
                yield "data: " + json.dumps({
                    "type": "tool_result",
                    "name": name,
                    "content": str(result)[:3000],
                }, ensure_ascii=False) + "\n\n"
                lc_msgs.append(ToolMessage(content=str(result), tool_call_id=tcid))

    except Exception as exc:
        _lg.getLogger(__name__).error("scenario agentic error: %s", exc, exc_info=True)
        yield f"data: {json.dumps({'type': 'token', 'content': f'[Agent error: {exc}]'})}\n\n"

    citations = [
        {
            "index": i + 1,
            "chunk_id": c["id"],
            "content": c["content"][:300],
            "source": c["metadata"].get("source_name") or c["metadata"].get("source_url", ""),
            "score": round(c.get("rerank_score", c.get("score", 0)), 4),
        }
        for i, c in enumerate(ctx.retrieved_chunks)
    ]
    yield f"data: {json.dumps({'type': 'citations', 'citations': citations})}\n\n"
    yield "data: [DONE]\n\n"


@router.get("/{scenario_id}")
async def get_public_scenario(scenario_id: str):
    """Public endpoint — get scenario info (name, description, UI config). No auth needed."""
    sc = await get_scenario(scenario_id)
    if not sc:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return {
        "id": sc["id"],
        "name": sc["name"],
        "description": sc["description"],
        "ui_config": sc.get("ui_config", {}),
    }


@router.post("/{scenario_id}/chat")
async def kb_chat(
    scenario_id: str,
    req: KbChatRequest,
    authorization: str | None = Header(None),
):
    """Public streaming RAG chat endpoint. Requires Bearer token authentication."""
    # Authenticate
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Bearer token")
    key_raw = authorization[len("Bearer "):]
    result = await verify_scenario_key(key_raw)
    if not result:
        raise HTTPException(status_code=403, detail="Invalid API key")
    verified_scenario_id, _key_id = result
    if verified_scenario_id != scenario_id:
        raise HTTPException(status_code=403, detail="API key does not match scenario")

    # Load scenario config
    sc = await get_scenario(scenario_id)
    if not sc:
        raise HTTPException(status_code=404, detail="Scenario not found")

    scenario_sources = await list_scenario_sources(scenario_id)

    if req.agentic:
        return StreamingResponse(
            _stream_kb_agentic(scenario_id, req, sc, scenario_sources),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return StreamingResponse(
        _stream_kb_chat(scenario_id, req, sc),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
