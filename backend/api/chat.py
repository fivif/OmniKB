from __future__ import annotations
import asyncio
import json
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import settings
from pipeline.embedder import embed_dense, embed_sparse
from storage.vector_store import hybrid_search

router = APIRouter()

_RAG_SYSTEM = (
    "You are OmniKB, a knowledgeable AI assistant. "
    "When relevant reference material from the user's knowledge base is provided, "
    "use it to supplement and enrich your answer. "
    "You are NOT limited to the provided context — draw on your own knowledge freely. "
    "Cite knowledge-base sources inline as [1], [2], etc. only when you actually use them. "
    "Never refuse to answer just because the context is limited."
)

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


async def _retrieve(query: str, top_k: int, filters: dict | None) -> list[dict]:
    dense = (await embed_dense([query]))[0]
    sparse = embed_sparse([query])[0]
    return await hybrid_search(
        query_dense=dense,
        query_sparse_indices=sparse[0],
        query_sparse_values=sparse[1],
        top_k=top_k,
        filters=filters,
    )


def _build_context(chunks: list[dict]) -> str:
    parts = []
    for i, c in enumerate(chunks, 1):
        src = c["metadata"].get("source_name") or c["metadata"].get("source_url", "unknown")
        parts.append(f"[{i}] Source: {src}\n{c['content']}")
    return "\n\n---\n\n".join(parts)


def _get_llm(provider: str, model: str):
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, api_key=settings.openai_api_key, streaming=True)
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model, api_key=settings.anthropic_api_key, streaming=True)
    if provider == "ollama":
        from langchain_community.chat_models import ChatOllama
        return ChatOllama(model=model, base_url=settings.ollama_base_url)
    if provider == "custom":
        # OpenAI-compatible third-party endpoint (e.g. SiliconFlow, DeepSeek, etc.)
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            api_key=settings.llm_api_key or "none",
            base_url=settings.llm_base_url or None,
            streaming=True,
        )
    raise ValueError(f"Unknown provider: {provider}")


async def _stream(req: ChatRequest) -> AsyncGenerator[str, None]:
    from storage.metadata_db import upsert_session

    provider = req.provider or settings.llm_provider
    model = req.model or settings.llm_model
    thread_id = req.thread_id or str(uuid.uuid4())

    user_query = next(
        (m.content for m in reversed(req.messages) if m.role == "user"), ""
    )

    chunks = await _retrieve(user_query, req.top_k, req.kb_filter)

    # Optional re-rank (disabled by default; enable via RERANKER_ENABLED=true in .env)
    if settings.reranker_enabled and chunks:
        from pipeline.reranker import rerank
        chunks = await asyncio.to_thread(
            rerank, user_query, chunks, settings.reranker_model, req.top_k
        )

    llm = _get_llm(provider, model)

    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    lc_msgs = [SystemMessage(content=_RAG_SYSTEM)]
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

    # Persist session to DB
    updated_messages = [m.model_dump() for m in req.messages] + [
        {"role": "assistant", "content": full_text}
    ]
    try:
        await upsert_session(thread_id, updated_messages)
    except Exception as _sess_err:
        import logging as _lg
        _lg.getLogger(__name__).warning("session persist failed for %s: %s", thread_id, _sess_err)

    yield f"data: {json.dumps({'type': 'session', 'thread_id': thread_id})}\n\n"
    yield "data: [DONE]\n\n"


@router.post("")
async def chat(req: ChatRequest):
    return StreamingResponse(
        _stream(req),
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
    provider = settings.llm_provider
    try:
        if provider == "custom":
            base = (settings.llm_base_url or "").rstrip("/")
            key = settings.llm_api_key or "none"
        elif provider == "openai":
            base = "https://api.openai.com/v1"
            key = settings.openai_api_key
        elif provider == "ollama":
            base = (settings.ollama_base_url or "http://localhost:11434").rstrip("/")
            key = "none"
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
