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

from config import settings
from pipeline.embedder import embed_dense, embed_sparse
from storage.vector_store import hybrid_search
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
    top_k: int = 5


def _build_context(chunks: list[dict]) -> str:
    parts = []
    for i, c in enumerate(chunks, 1):
        src = c["metadata"].get("source_name") or c["metadata"].get("source_url", "unknown")
        parts.append(f"[{i}] Source: {src}\n{c['content']}")
    return "\n\n---\n\n".join(parts)


def _get_llm(provider: str, model: str, base_url: str, api_key: str):
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, api_key=api_key, streaming=True)
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model, api_key=api_key, streaming=True)
    if provider == "ollama":
        from langchain_community.chat_models import ChatOllama
        return ChatOllama(model=model, base_url=base_url)
    if provider == "custom":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            api_key=api_key or "none",
            base_url=base_url or None,
            streaming=True,
        )
    raise ValueError(f"Unknown provider: {provider}")


async def _retrieve_chunks(query: str, scenario_id: str, top_k: int) -> list[dict]:
    """Retrieve chunks from vector store, filtered to scenario's allowed chunks."""
    import logging as _lg

    from storage.metadata_db import list_chunks_by_source

    # Get allowed chunk IDs for this scenario
    scenario_sources = await list_scenario_sources(scenario_id)
    allowed_chunk_ids: set[str] = set()

    for s in scenario_sources:
        if s["chunk_id"]:
            # Specific chunk reference
            allowed_chunk_ids.add(s["chunk_id"])
        elif s["source_id"]:
            # Whole-source reference — expand to all chunks of that source
            try:
                chunks = await list_chunks_by_source(s["source_id"], limit=10000)
                allowed_chunk_ids.update(c["id"] for c in chunks)
            except Exception:
                pass

    if not allowed_chunk_ids:
        return []

    try:
        dense = (await embed_dense([query]))[0]
    except Exception as exc:
        _lg.getLogger(__name__).warning("Dense embedding failed: %s", exc)
        return []

    sparse = None
    try:
        sparse = embed_sparse([query])[0]
    except Exception:
        pass

    try:
        results = await hybrid_search(
            query_dense=dense,
            query_sparse_indices=sparse[0] if sparse else [],
            query_sparse_values=sparse[1] if sparse else [],
            top_k=top_k * 3,  # over-fetch, then filter
            filters=None,
        )
    except Exception as exc:
        _lg.getLogger(__name__).warning("Hybrid search failed: %s", exc)
        return []

    # Filter to allowed chunks only
    filtered = [c for c in results if c["id"] in allowed_chunk_ids]
    return filtered[:top_k]


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

    user_query = next(
        (m.content for m in reversed(req.messages) if m.role == "user"), ""
    )

    # Retrieve from vector store filtered by scenario chunks
    chunks = await _retrieve_chunks(user_query, scenario_id, req.top_k)

    # Rerank if enabled
    if settings.reranker_enabled and chunks:
        try:
            from pipeline.reranker import rerank
            chunks = await asyncio.to_thread(
                rerank, user_query, chunks, settings.reranker_model
            )
        except Exception as exc:
            _lg.getLogger(__name__).warning("Reranker failed, using unranked chunks: %s", exc)

    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    system_prompt = sc.get("system_prompt") or (
        "You are a helpful knowledge base assistant. "
        "Use the provided context to answer the user's question accurately. "
        "Cite sources as [1], [2], etc. when using them."
    )

    lc_msgs = [SystemMessage(content=system_prompt)]
    for msg in req.messages[:-1]:
        if msg.role == "user":
            lc_msgs.append(HumanMessage(content=msg.content))
        elif msg.role == "assistant":
            lc_msgs.append(AIMessage(content=msg.content))

    ctx_template = (
        "Relevant knowledge base excerpts:\n\n{chunks}\n\nUser question: {question}"
        if chunks
        else "{question}"
    )

    if chunks:
        ctx_str = _build_context(chunks)
        final_user = ctx_template.format(chunks=ctx_str, question=user_query)
    else:
        final_user = ctx_template.format(question=user_query)

    lc_msgs.append(HumanMessage(content=final_user))

    llm = _get_llm(provider, model, base_url, api_key)
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

    return StreamingResponse(
        _stream_kb_chat(scenario_id, req, sc),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
