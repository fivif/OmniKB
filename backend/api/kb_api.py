"""Public KB Q&A API — Bearer-token authenticated, scenario-scoped RAG chat.

External applications call ``POST /kb/{scenario_id}/chat`` with a Bearer token
(one of the scenario's API keys) to get streaming RAG responses filtered to the
scenario's selected chunks.

The streaming logic is delegated to ``api/chat.py`` — only the knowledge base
scope and auth differ from the internal chat panel.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from qdrant_client.models import Filter, FieldCondition, MatchAny, HasIdCondition

from config import settings
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
    agentic: bool = True
    """When true (default), the LLM may call KB tools within the scenario scope."""


def _build_qdrant_filter(scenario_sources: list[dict]) -> object | None:
    """Build a Qdrant Filter from scenario source/chunk bindings."""
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
    return Filter(should=[
        FieldCondition(key="source_id", match=MatchAny(any=whole_source_ids)),
        HasIdCondition(has_id=specific_chunk_ids),
    ])


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

    # Load scenario config and sources
    sc = await get_scenario(scenario_id)
    if not sc:
        raise HTTPException(status_code=404, detail="Scenario not found")
    scenario_sources = await list_scenario_sources(scenario_id)

    # Build scenario-scoped filter
    qdrant_filter = _build_qdrant_filter(scenario_sources)

    # Scenario LLM overrides
    provider = sc.get("llm_provider") or settings.llm_provider
    model = sc.get("llm_model") or settings.llm_model
    base_url = sc.get("llm_base_url") or settings.llm_base_url
    api_key = sc.get("llm_api_key") or settings.llm_api_key or "none"
    system_prompt = sc.get("system_prompt") or None

    # Convert KbChatMessage list → chat.Message list
    from api.chat import Message as ChatMsg, ChatRequest, _stream, _stream_agentic

    chat_req = ChatRequest(
        messages=[ChatMsg(role=m.role, content=m.content) for m in req.messages],
        top_k=req.top_k,
    )

    if req.agentic is False:
        return StreamingResponse(
            _stream(chat_req, system_prompt=system_prompt,
                    provider=provider, model=model,
                    base_url=base_url, api_key=api_key,
                    qdrant_filter=qdrant_filter, skip_session=True),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return StreamingResponse(
        _stream_agentic(chat_req, system_prompt=system_prompt,
                        provider=provider, model=model,
                        base_url=base_url, api_key=api_key,
                        qdrant_filter=qdrant_filter),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
