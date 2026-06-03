"""Scenario management API — multi-tenancy KB Q&A builder."""

from __future__ import annotations

import hashlib
import re
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
    list_scenario_source_ids,
    list_scenario_sources,
    list_scenarios,
    remove_scenario_source,
    update_scenario,
)
router = APIRouter()


# ── Request/response models ──────────────────────────────────────

_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")

class ScenarioCreate(BaseModel):
    name: str = "未命名场景"
    description: str = ""
    system_prompt: str = ""
    llm_provider: str = "deepseek"
    llm_model: str = ""
    llm_base_url: str = ""
    llm_api_key: str = ""
    slug: str | None = None
    ui_config: dict | None = None


class ScenarioUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    slug: str | None = None
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


def _normalize_scenario_llm_fields(data: dict) -> dict:
    from agents.llm import normalize_provider

    normalized = dict(data)
    normalized["llm_provider"] = normalize_provider(
        normalized.get("llm_provider"),
        model=normalized.get("llm_model", ""),
        base_url=normalized.get("llm_base_url", ""),
    )
    return normalized


# ── Scenario CRUD ────────────────────────────────────────────────

@router.get("")
async def list_all_scenarios():
    scenarios = [_normalize_scenario_llm_fields(sc) for sc in await list_scenarios()]
    return {"scenarios": scenarios}


@router.get("/{scenario_id}")
async def get_one_scenario(scenario_id: str):
    sc = await get_scenario(scenario_id)
    if not sc:
        raise HTTPException(status_code=404, detail="Scenario not found")
    sc = _normalize_scenario_llm_fields(sc)
    sc["source_count"] = await count_scenario_sources(scenario_id)
    return sc


@router.post("")
async def create_scenario(body: ScenarioCreate):
    # Validate slug if provided
    slug = body.slug
    if slug is not None:
        slug = slug.strip()
        if not slug:
            slug = None
        elif len(slug) > 30:
            raise HTTPException(status_code=400, detail="Slug must be at most 30 characters")
        elif not _SLUG_RE.match(slug):
            raise HTTPException(status_code=400, detail="Slug must be lowercase alphanumeric with optional hyphens (e.g. my-support-bot)")
    if slug is None:
        slug = secrets.token_hex(4)  # 8-char random hex

    sc = {
        "id": str(uuid.uuid4()),
        "slug": slug,
        "name": body.name,
        "description": body.description,
        "system_prompt": body.system_prompt,
        "llm_provider": body.llm_provider,
        "llm_model": body.llm_model,
        "llm_base_url": body.llm_base_url,
        "llm_api_key": body.llm_api_key,
        "ui_config": body.ui_config or {},
    }
    sc = _normalize_scenario_llm_fields(sc)
    await insert_scenario(sc)
    sc["source_count"] = 0
    return sc


@router.put("/{scenario_id}")
async def update_one_scenario(scenario_id: str, body: ScenarioUpdate):
    existing = await get_scenario(scenario_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Scenario not found")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}

    # Validate slug if provided
    if "slug" in updates:
        slug = updates["slug"].strip()
        if not slug:
            del updates["slug"]
        elif len(slug) > 30:
            raise HTTPException(status_code=400, detail="Slug must be at most 30 characters")
        elif not _SLUG_RE.match(slug):
            raise HTTPException(status_code=400, detail="Slug must be lowercase alphanumeric with optional hyphens (e.g. my-support-bot)")
        else:
            updates["slug"] = slug

    if {"llm_provider", "llm_model", "llm_base_url"} & set(updates):
        merged = {**existing, **updates}
        updates["llm_provider"] = _normalize_scenario_llm_fields(merged)["llm_provider"]
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

    # Find wiki pages that reference the added source_ids, notify caller
    wiki_linked = 0
    added_source_ids = {e[0] for e in entries if e[0]}
    if added_source_ids:
        try:
            from config import settings as _s
            _wiki_on = getattr(_s, "wiki_retrieval_enabled", True)
        except Exception:
            _wiki_on = True
        if _wiki_on:
            try:
                from storage.metadata_db import list_wiki_pages as _lwp
                all_pages = await _lwp(limit=2000)
                for p in all_pages:
                    p_sids = set(p.get("source_ids") or [])
                    if added_source_ids & p_sids:
                        wiki_linked += 1
            except Exception:
                pass

    return {"status": "ok", "added": count, "wiki_linked": wiki_linked}


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

async def _search_and_format(
    query: str,
    top_k: int,
    *,
    content_max_len: int = 500,
    include_chunk_index: bool = False,
) -> list[dict]:
    """Semantic search helper — RAG removed, always returns empty."""
    return []


@router.post("/agent/search-chunks")
async def agent_search_chunks(body: AgentSearchRequest):
    """Search across the knowledge base to find relevant chunks.

    Used by the agent to suggest chunks when building a scenario.
    RAG removed — chunk search returns empty; wiki retrieval still active.
    """
    chunks: list[dict] = []

    # ── Wiki retrieval (best-effort) ──────────────────────────
    wiki_hits = []
    if getattr(settings, "wiki_retrieval_enabled", False):
        try:
            from wiki.retriever import search_wiki_pages
            hits = await search_wiki_pages(query=body.query, top_k=5)
            wiki_hits = [
                {
                    "page_id": h.page_id,
                    "page_type": h.page_type,
                    "title": h.title,
                    "slug": h.slug,
                    "summary": h.summary,
                    "score": h.score,
                }
                for h in hits
            ]
        except Exception:
            pass

    return {"chunks": chunks, "query": body.query, "wiki_hits": wiki_hits}


# ── Agent-assisted scenario management ────────────────────────────

def _sanitize_ui_css(css: str) -> str:
    import re

    cleaned = str(css or "")
    # Block @import and @charset directives
    cleaned = re.sub(r"@import\b", "/* blocked */", cleaned, flags=re.I)
    cleaned = re.sub(r"@charset\b", "/* blocked */", cleaned, flags=re.I)
    # Block url(...) external resource loads
    cleaned = re.sub(r"url\s*\(", "url(/* blocked */", cleaned, flags=re.I)
    # Block CSS expression(), behavior:, -moz-binding:, javascript: URI
    cleaned = re.sub(r"expression\s*\(", "/* blocked */", cleaned, flags=re.I)
    cleaned = re.sub(r"behavior\s*:", "/* blocked */:", cleaned, flags=re.I)
    cleaned = re.sub(r"-moz-binding\s*:", "/* blocked */:", cleaned, flags=re.I)
    cleaned = re.sub(r"javascript\s*:", "/* blocked */:", cleaned, flags=re.I)
    # Block backslash-escaped bypass patterns (e.g. \0065xpressio\06e)
    cleaned = re.sub(r"\\[0-9a-fA-F]{1,6}\s?", "", cleaned)
    return cleaned


def _sanitize_full_page_html(html: str) -> str:
    """Strip scripts and event handlers from full-page HTML."""
    import re

    s = str(html)[:50000]  # max 50 KB
    s = re.sub(r'<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\son\w+\s*=\s*"[^"]*"', '', s)
    s = re.sub(r'\son\w+\s*=\s*\'[^\']*\'', '', s)
    s = re.sub(r'javascript\s*:', 'blocked:', s, flags=re.IGNORECASE)
    return s


def _sanitize_page_js(js: str) -> str:
    """Block dangerous APIs in agent-written JS."""
    s = str(js)[:8000]
    for banned in ('fetch(', 'XMLHttpRequest', 'eval(', 'import(', 'document.cookie', 'localStorage.', 'sessionStorage.'):
        s = s.replace(banned, '/* blocked */')
    return s


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
- update_llm: {{"action":"update_llm","changes":{{"llm_provider":"deepseek|custom","llm_model":"...","llm_base_url":"...","llm_api_key":"..."}}}}
- inject_html: {{"action":"inject_html","selector":"#css-selector","mode":"replace|append|prepend","html":"<div>Safe HTML content</div>"}} — inject DOM into the current page. Use replace to overwrite an element, append to add at the end, prepend to add at the beginning. HTML is sanitized so scripts and event handlers are stripped. Great for adding banners, restructuring sections, or injecting informational blocks.
- execute_script: {{"action":"execute_script","script":"document.title = 'New Title'; console.log('done');"}} — run arbitrary JavaScript on the page (max 2000 chars). Use for programmatic DOM changes, triggering events, or calling frontend APIs. Be conservative and safe.
- rewrite_full_page: Rewrite the ENTIRE standalone Q&A page HTML/CSS/JS. Use this for complete redesigns.
  {{"action":"rewrite_full_page","changes":{{"page_html":"<complete HTML>","page_css":"<CSS>","page_js":"<JS>"}}}}
  Keep these element IDs: chat-messages, chat-input, btn-send, welcome-message, btn-clear-chat, btn-reset-page, btn-show-key-modal, key-modal-backdrop, chat-disclaimer
  page_html replaces the body content. page_css is injected into <style id="custom-css">. page_js is injected at page end.
- reset_page: Restore the standalone Q&A page to its default template.
  {{"action":"reset_page"}}

Rules:
- When the user wants a major visual redesign, prefer ONE update_ui action that first chooses the best template and then rewrites multiple UI fields together.
- You may change template, title, subtitle, welcome, placeholder, disclaimer, color and css in the same update_ui action.
- CSS may only target .kbchat-body and .kbchat-* selectors. Never use @import or external URLs.
- Search before adding or removing chunks. Never invent chunk IDs.
- Use inject_html and execute_script for page-level changes that go beyond UI config fields. Explain what you are doing in the reply.
- Only output JSON."""


class AgentAssistRequest(BaseModel):
    message: str


class AgentAssistResponse(BaseModel):
    reply: str
    actions_performed: list[str]
    raw_actions: list[dict] | None = None
    search_results: list[dict] | None = None
    wiki_hits: list[dict] | None = None


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
    from agents.llm import build_chat_model, normalize_provider

    normalized_provider = normalize_provider(
        provider,
        model=model,
        base_url=app_settings.llm_base_url,
    )
    llm = build_chat_model(
        normalized_provider,
        model,
        api_key=app_settings.llm_api_key,
        base_url=app_settings.llm_base_url,
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
    raw_actions: list[dict] = []
    search_results = None
    wiki_hits = None

    for action in actions:
        if not isinstance(action, dict):
            continue
        act_type = action.get("action", "")

        if act_type == "search_chunks":
            q = str(action.get("query", body.message))
            search_results = await _search_and_format(q, 10, content_max_len=300)
            if search_results:
                performed.append(f"搜索了「{q}」，找到 {len(search_results)} 个结果")
            else:
                performed.append(f"搜索「{q}」无结果")
            # ── Wiki search alongside chunk search ────────────
            if getattr(settings, "wiki_retrieval_enabled", False):
                try:
                    from wiki.retriever import search_wiki_pages
                    # Filter wiki results to pages whose source_ids overlap
                    # with the scenario's source_ids (whole-source refs only)
                    scenario_sids = await list_scenario_source_ids(scenario_id)
                    source_kwargs = {}
                    if scenario_sids:
                        source_kwargs["source_ids"] = scenario_sids
                    hits = await search_wiki_pages(query=q, top_k=5, **source_kwargs)
                    wiki_hits = [
                        {
                            "page_id": h.page_id,
                            "page_type": h.page_type,
                            "title": h.title,
                            "slug": h.slug,
                            "summary": h.summary,
                            "score": h.score,
                        }
                        for h in hits
                    ]
                except Exception:
                    pass

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
                    merged = {**sc, **valid}
                    valid["llm_provider"] = _normalize_scenario_llm_fields(merged)["llm_provider"]
                    await update_scenario(scenario_id, valid)
                    performed.append(f"更新了 LLM: {', '.join(valid.keys())}")

        elif act_type == "update_ui":
            changes = action.get("changes", {})
            if isinstance(changes, dict):
                ui_current = dict(sc.get("ui_config", {}) or {})
                allowed = ("template", "title", "subtitle", "welcome", "placeholder", "disclaimer", "color", "css",
                           "page_html", "page_css", "page_js")
                for k in allowed:
                    if k not in changes or changes[k] is None:
                        continue
                    if k == "template" and str(changes[k]) not in {"assistant", "guide", "support"}:
                        continue
                    if k == "css":
                        ui_current[k] = _sanitize_ui_css(str(changes[k]))
                    elif k == "page_html":
                        ui_current[k] = _sanitize_full_page_html(str(changes[k]))
                    elif k == "page_css":
                        ui_current[k] = _sanitize_ui_css(str(changes[k]))
                    elif k == "page_js":
                        ui_current[k] = _sanitize_page_js(str(changes[k]))
                    else:
                        ui_current[k] = changes[k]
                await update_scenario(scenario_id, {"ui_config": ui_current})
                keys = [k for k in allowed if k in changes]
                performed.append(f"更新了 UI: {', '.join(keys)}")

        elif act_type == "inject_html":
            selector = str(action.get("selector", "")).strip()
            mode = str(action.get("mode", "")).strip()
            html = str(action.get("html", ""))
            if not selector:
                performed.append("❌ inject_html: selector 不能为空")
            elif mode not in ("replace", "append", "prepend"):
                performed.append(f"❌ inject_html: 无效 mode={mode}，仅支持 replace/append/prepend")
            elif not html:
                performed.append("❌ inject_html: html 不能为空")
            else:
                performed.append(f"✅ 已注入 HTML 到: {selector} (mode={mode})")
                raw_actions.append({"action": "inject_html", "selector": selector, "mode": mode, "html": html})

        elif act_type == "execute_script":
            script = str(action.get("script", ""))
            if not script:
                performed.append("❌ execute_script: script 不能为空")
            elif len(script) > 2000:
                performed.append(f"❌ execute_script: 脚本过长 ({len(script)} chars, max 2000)")
            else:
                performed.append("✅ 已执行脚本")
                raw_actions.append({"action": "execute_script", "script": script})

        elif act_type == "rewrite_full_page":
            changes = action.get("changes", {})
            if isinstance(changes, dict):
                ui_current = dict(sc.get("ui_config", {}) or {})
                if "page_html" in changes:
                    ui_current["page_html"] = _sanitize_full_page_html(str(changes["page_html"]))
                if "page_css" in changes:
                    ui_current["page_css"] = _sanitize_ui_css(str(changes["page_css"]))
                if "page_js" in changes:
                    ui_current["page_js"] = _sanitize_page_js(str(changes["page_js"]))
                await update_scenario(scenario_id, {"ui_config": ui_current})
                performed.append("已重写完整问答页面")

        elif act_type == "reset_page":
            ui_current = dict(sc.get("ui_config", {}) or {})
            for key in ("page_html", "page_css", "page_js"):
                ui_current.pop(key, None)
            await update_scenario(scenario_id, {"ui_config": ui_current})
            performed.append("已重置问答页面到默认模板")

    return AgentAssistResponse(
        reply=reply,
        actions_performed=performed,
        raw_actions=raw_actions if raw_actions else None,
        search_results=search_results,
        wiki_hits=wiki_hits,
    )
