"""Scenario management API — multi-tenancy KB Q&A builder."""

from __future__ import annotations

import hashlib
import secrets
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from storage.metadata_db import (
    add_scenario_sources_batch,
    count_scenario_sources,
    delete_scenario,
    delete_scenario_key,
    get_scenario,
    insert_scenario,
    insert_scenario_key,
    list_scenario_keys,
    list_scenario_sources,
    list_scenarios,
    remove_scenario_source,
    update_scenario,
)
from storage.vector_store import hybrid_search
from pipeline.embedder import embed_dense, embed_sparse

router = APIRouter()


# ── Request/response models ──────────────────────────────────────

class ScenarioCreate(BaseModel):
    name: str = "未命名场景"
    description: str = ""
    system_prompt: str = ""
    llm_provider: str = "custom"
    llm_model: str = ""
    llm_base_url: str = ""
    llm_api_key: str = ""
    ui_config: dict | None = None


class ScenarioUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    ui_config: dict | None = None


class ScenarioSourceAdd(BaseModel):
    source_id: str
    chunk_id: str = ""
    added_by: str = "manual"


class ScenarioSourcesBatch(BaseModel):
    entries: list[ScenarioSourceAdd]
    added_by: str = "manual"


class ScenarioSourceRemove(BaseModel):
    source_id: str
    chunk_id: str = ""


class ApiKeyCreate(BaseModel):
    key_name: str = ""


class ApiKeyResponse(BaseModel):
    id: str
    key_name: str
    key_prefix: str
    raw_key: str  # only returned on creation
    created_at: str


class AgentSearchRequest(BaseModel):
    query: str
    top_k: int = 20


# ── Scenario CRUD ────────────────────────────────────────────────

@router.get("")
async def list_all_scenarios():
    return {"scenarios": await list_scenarios()}


@router.get("/{scenario_id}")
async def get_one_scenario(scenario_id: str):
    sc = await get_scenario(scenario_id)
    if not sc:
        raise HTTPException(status_code=404, detail="Scenario not found")
    sc["source_count"] = await count_scenario_sources(scenario_id)
    return sc


@router.post("")
async def create_scenario(body: ScenarioCreate):
    sc = {
        "id": str(uuid.uuid4()),
        "name": body.name,
        "description": body.description,
        "system_prompt": body.system_prompt,
        "llm_provider": body.llm_provider,
        "llm_model": body.llm_model,
        "llm_base_url": body.llm_base_url,
        "llm_api_key": body.llm_api_key,
        "ui_config": body.ui_config or {},
    }
    await insert_scenario(sc)
    sc["source_count"] = 0
    return sc


@router.put("/{scenario_id}")
async def update_one_scenario(scenario_id: str, body: ScenarioUpdate):
    existing = await get_scenario(scenario_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Scenario not found")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if updates:
        await update_scenario(scenario_id, updates)
    return await get_one_scenario(scenario_id)


@router.delete("/{scenario_id}")
async def delete_one_scenario(scenario_id: str):
    existing = await get_scenario(scenario_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Scenario not found")
    await delete_scenario(scenario_id)
    return {"status": "deleted", "scenario_id": scenario_id}


# ── Scenario sources (chunk management) ──────────────────────────

@router.get("/{scenario_id}/sources")
async def list_scenario_sources_endpoint(scenario_id: str):
    existing = await get_scenario(scenario_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return {"sources": await list_scenario_sources(scenario_id)}


@router.post("/{scenario_id}/sources")
async def add_scenario_sources_endpoint(scenario_id: str, body: ScenarioSourcesBatch):
    existing = await get_scenario(scenario_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Scenario not found")
    entries = [(e.source_id, e.chunk_id) for e in body.entries]
    count = await add_scenario_sources_batch(scenario_id, entries, body.added_by)
    return {"status": "ok", "added": count}


@router.delete("/{scenario_id}/sources")
async def remove_scenario_source_endpoint(scenario_id: str, body: ScenarioSourceRemove):
    existing = await get_scenario(scenario_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Scenario not found")
    await remove_scenario_source(scenario_id, body.source_id, body.chunk_id)
    return {"status": "removed"}


# ── API keys ─────────────────────────────────────────────────────

@router.get("/{scenario_id}/keys")
async def list_keys(scenario_id: str):
    existing = await get_scenario(scenario_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return {"keys": await list_scenario_keys(scenario_id)}


@router.post("/{scenario_id}/keys")
async def create_key(scenario_id: str, body: ApiKeyCreate):
    existing = await get_scenario(scenario_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Scenario not found")

    raw_key = f"sk-{secrets.token_hex(24)}"
    key_prefix = raw_key[:11]  # "sk-" + first 8 hex chars
    key_id = str(uuid.uuid4())

    await insert_scenario_key({
        "id": key_id,
        "scenario_id": scenario_id,
        "key_name": body.key_name,
        "key_hash": hashlib.sha256(raw_key.encode()).hexdigest(),
        "key_prefix": key_prefix,
        "created_at": None,
        "last_used_at": None,
    })

    return {
        "id": key_id,
        "key_name": body.key_name,
        "key_prefix": key_prefix,
        "raw_key": raw_key,
        "scenario_id": scenario_id,
    }


@router.delete("/{scenario_id}/keys/{key_id}")
async def delete_key(scenario_id: str, key_id: str):
    existing = await get_scenario(scenario_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Scenario not found")
    await delete_scenario_key(key_id)
    return {"status": "deleted", "key_id": key_id}


# ── Agent-assisted chunk search ──────────────────────────────────

@router.post("/agent/search-chunks")
async def agent_search_chunks(body: AgentSearchRequest):
    """Semantic search across the knowledge base to find relevant chunks.

    Used by the agent to suggest chunks when building a scenario.
    """
    import logging as _lg

    try:
        dense = (await embed_dense([body.query]))[0]
    except Exception as exc:
        _lg.getLogger(__name__).warning("Dense embed failed for agent search: %s", exc)
        return {"chunks": [], "query": body.query}

    sparse = None
    try:
        sparse = embed_sparse([body.query])[0]
    except Exception:
        pass

    try:
        results = await hybrid_search(
            query_dense=dense,
            query_sparse_indices=sparse[0] if sparse else [],
            query_sparse_values=sparse[1] if sparse else [],
            top_k=body.top_k,
            filters=None,
        )
    except Exception as exc:
        _lg.getLogger(__name__).warning("Hybrid search failed for agent: %s", exc)
        return {"chunks": [], "query": body.query}

    chunks = [
        {
            "id": c["id"],
            "content": c["content"][:500],
            "source_id": c["metadata"].get("source_id", ""),
            "source_name": c["metadata"].get("source_name", ""),
            "chunk_index": c["metadata"].get("chunk_index", 0),
            "score": round(c.get("score", 0), 4),
        }
        for c in results
    ]
    return {"chunks": chunks, "query": body.query}


# ── Agent-assisted scenario management ────────────────────────────

def _sanitize_ui_css(css: str) -> str:
    import re

    cleaned = str(css or "")
    cleaned = re.sub(r"@import\b", "/* blocked */", cleaned, flags=re.I)
    cleaned = re.sub(r"url\s*\(", "url(/* blocked */", cleaned, flags=re.I)
    return cleaned

def _build_agent_prompt(
    name: str, description: str, system_prompt: str,
    llm_provider: str, llm_model: str,
    ui_template: str, ui_title: str, ui_subtitle: str,
    ui_color: str, ui_welcome: str, ui_placeholder: str,
    ui_disclaimer: str, ui_css_preview: str,
    chunk_count: int,
) -> str:
    """Build the agent system prompt with scenario state injected."""
    return f"""You are a scenario configuration assistant for OmniKB. Based on the user's request, output a JSON object only.

Current scenario:
- name: "{name}"
- description: "{description}"
- system_prompt: "{system_prompt}"
- llm: {llm_provider}/{llm_model}
- ui_template: "{ui_template}"
- ui_title: "{ui_title}"
- ui_subtitle: "{ui_subtitle}"
- ui_welcome: "{ui_welcome}"
- ui_placeholder: "{ui_placeholder}"
- ui_disclaimer: "{ui_disclaimer}"
- ui_color: "{ui_color}"
- ui_css_preview: "{ui_css_preview}"
- chunks: {chunk_count}

Available templates:
- assistant: clean knowledge copilot, cool light tone, suitable for general KB search.
- guide: warm explainer, better for teaching, storytelling, walkthroughs and structured explanation.
- support: dark support desk, suitable for FAQ, troubleshooting and customer support.

Output ONLY this JSON structure (no markdown, no extra text):
{{"reply": "<friendly Chinese reply, 1-2 sentences>", "actions": []}}

Available actions:
- search_chunks: {{"action":"search_chunks","query":"<search terms>"}}
- add_chunks: {{"action":"add_chunks","chunk_ids":["..."],"source_ids":["..."]}}
- remove_chunks: {{"action":"remove_chunks","chunk_ids":["..."],"source_ids":["..."]}}
- update_ui: {{"action":"update_ui","changes":{{"template":"assistant|guide|support","title":"...","subtitle":"...","welcome":"...","placeholder":"...","disclaimer":"...","color":"#hex","css":"..."}}}}
- update_config: {{"action":"update_config","changes":{{"name":"...","description":"...","system_prompt":"..."}}}}
- update_llm: {{"action":"update_llm","changes":{{"llm_provider":"...","llm_model":"...","llm_base_url":"...","llm_api_key":"..."}}}}

Rules:
- When the user wants a major visual redesign, prefer ONE update_ui action that first chooses the best template and then rewrites multiple UI fields together.
- You may change template, title, subtitle, welcome, placeholder, disclaimer, color and css in the same update_ui action.
- CSS may only target .kbchat-body and .kbchat-* selectors. Never use @import or external URLs.
- Search before adding or removing chunks. Never invent chunk IDs.
- Only output JSON."""


class AgentAssistRequest(BaseModel):
    message: str


class AgentAssistResponse(BaseModel):
    reply: str
    actions_performed: list[str]
    search_results: list[dict] | None = None


def _extract_json(text: str) -> dict | None:
    """Robust JSON extraction from LLM output."""
    import json as _json
    import re

    text = text.strip()

    # Remove markdown fences
    if text.startswith("```"):
        text = re.sub(r'^```\w*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)

    # Try direct parse first
    try:
        return _json.loads(text)
    except _json.JSONDecodeError:
        pass

    # Find first { and matching }
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return _json.loads(text[start:i+1])
                except _json.JSONDecodeError:
                    pass
                break

    return None


@router.post("/{scenario_id}/agent/assist")
async def agent_assist(scenario_id: str, body: AgentAssistRequest):
    """Agent chat endpoint — interpret natural language and modify the scenario."""
    import logging as _lg
    logger = _lg.getLogger(__name__)

    sc = await get_scenario(scenario_id)
    if not sc:
        raise HTTPException(status_code=404, detail="Scenario not found")

    ui = sc.get("ui_config", {}) or {}
    chunk_count = await count_scenario_sources(scenario_id)

    system_prompt = _build_agent_prompt(
        name=sc.get("name", ""),
        description=(sc.get("description", "") or "")[:100],
        system_prompt=(sc.get("system_prompt", "") or "")[:150],
        llm_provider=sc.get("llm_provider") or "default",
        llm_model=sc.get("llm_model") or "default",
        ui_template=ui.get("template", "assistant"),
        ui_title=ui.get("title", ""),
        ui_subtitle=ui.get("subtitle", ""),
        ui_color=ui.get("color", "#a78bfa"),
        ui_welcome=ui.get("welcome", ""),
        ui_placeholder=ui.get("placeholder", ""),
        ui_disclaimer=ui.get("disclaimer", ""),
        ui_css_preview=(ui.get("css", "") or "")[:240],
        chunk_count=chunk_count,
    )

    from config import settings as app_settings
    from langchain_core.messages import HumanMessage, SystemMessage

    # Always use system LLM config
    provider = app_settings.llm_provider
    model = app_settings.llm_model

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(model=model, api_key=app_settings.openai_api_key or "none")
    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        llm = ChatAnthropic(model=model, api_key=app_settings.anthropic_api_key or "none")
    elif provider == "ollama":
        from langchain_community.chat_models import ChatOllama
        llm = ChatOllama(model=model, base_url=app_settings.ollama_base_url)
    else:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            model=model,
            api_key=app_settings.llm_api_key or "none",
            base_url=app_settings.llm_base_url or None,
        )

    try:
        resp = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=body.message),
        ])
        raw = (resp.content or "").strip()
    except Exception as exc:
        logger.warning("Agent assist LLM call failed: %s", exc)
        return AgentAssistResponse(
            reply=f"抱歉，LLM 调用失败: {exc}。请检查系统 LLM 配置是否正确。",
            actions_performed=[],
        )

    parsed = _extract_json(raw)
    if parsed is None:
        logger.warning("Agent assist JSON parse failed. Raw: %s", raw[:300])
        return AgentAssistResponse(
            reply=f"收到回复但无法解析指令。请换一种方式描述你的需求。\n\n原始回复: {raw[:300]}",
            actions_performed=[],
        )

    reply = str(parsed.get("reply", "已完成。"))
    actions = parsed.get("actions", [])
    if not isinstance(actions, list):
        actions = []

    performed: list[str] = []
    search_results = None

    for action in actions:
        if not isinstance(action, dict):
            continue
        act_type = action.get("action", "")

        if act_type == "search_chunks":
            q = str(action.get("query", body.message))
            try:
                dense = (await embed_dense([q]))[0]
                sparse_raw = embed_sparse([q])
                sparse = sparse_raw[0] if sparse_raw else None
                results = await hybrid_search(
                    query_dense=dense,
                    query_sparse_indices=sparse[0] if sparse else [],
                    query_sparse_values=sparse[1] if sparse else [],
                    top_k=10,
                    filters=None,
                )
                search_results = [
                    {
                        "id": c["id"],
                        "content": c["content"][:300],
                        "source_id": c["metadata"].get("source_id", ""),
                        "source_name": c["metadata"].get("source_name", ""),
                        "score": round(c.get("score", 0), 4),
                    }
                    for c in results
                ]
                performed.append(f"搜索了「{q}」，找到 {len(search_results)} 个结果")
            except Exception as exc:
                logger.warning("Agent search failed: %s", exc)
                performed.append(f"搜索失败: {exc}")

        elif act_type == "add_chunks":
            chunk_ids = action.get("chunk_ids", [])
            source_ids = action.get("source_ids", [])
            if not isinstance(chunk_ids, list):
                chunk_ids = []
            if not isinstance(source_ids, list):
                source_ids = []
            entries = []
            for i, cid in enumerate(chunk_ids):
                sid = str(source_ids[i]) if i < len(source_ids) else ""
                entries.append((sid, str(cid)))
            if entries:
                cnt = await add_scenario_sources_batch(scenario_id, entries, added_by="agent")
                performed.append(f"添加了 {cnt} 个片段到场景")
            else:
                performed.append("未找到要添加的片段")

        elif act_type == "remove_chunks":
            chunk_ids = action.get("chunk_ids", [])
            source_ids = action.get("source_ids", [])
            if not isinstance(chunk_ids, list):
                chunk_ids = []
            if not isinstance(source_ids, list):
                source_ids = []
            for i, cid in enumerate(chunk_ids):
                sid = str(source_ids[i]) if i < len(source_ids) else ""
                await remove_scenario_source(scenario_id, sid, str(cid))
            performed.append(f"移除了 {len(chunk_ids)} 个片段")

        elif act_type == "update_config":
            changes = action.get("changes", {})
            if isinstance(changes, dict):
                valid = {k: v for k, v in changes.items()
                         if k in ("name", "description", "system_prompt") and v is not None}
                if valid:
                    await update_scenario(scenario_id, valid)
                    performed.append(f"更新了配置: {', '.join(valid.keys())}")

        elif act_type == "update_llm":
            changes = action.get("changes", {})
            if isinstance(changes, dict):
                valid = {k: v for k, v in changes.items()
                         if k in ("llm_provider", "llm_model", "llm_base_url", "llm_api_key") and v is not None}
                if valid:
                    await update_scenario(scenario_id, valid)
                    performed.append(f"更新了 LLM: {', '.join(valid.keys())}")

        elif act_type == "update_ui":
            changes = action.get("changes", {})
            if isinstance(changes, dict):
                ui_current = dict(sc.get("ui_config", {}) or {})
                allowed = ("template", "title", "subtitle", "welcome", "placeholder", "disclaimer", "color", "css")
                for k in allowed:
                    if k not in changes or changes[k] is None:
                        continue
                    if k == "template" and str(changes[k]) not in {"assistant", "guide", "support"}:
                        continue
                    if k == "css":
                        ui_current[k] = _sanitize_ui_css(str(changes[k]))
                    else:
                        ui_current[k] = changes[k]
                await update_scenario(scenario_id, {"ui_config": ui_current})
                keys = [k for k in allowed if k in changes]
                performed.append(f"更新了 UI: {', '.join(keys)}")

    return AgentAssistResponse(
        reply=reply,
        actions_performed=performed,
        search_results=search_results,
    )
