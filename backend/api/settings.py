"""Runtime settings — proxy, local model download, and live-config endpoints."""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter()
logger = logging.getLogger(__name__)


class ProxyUpdate(BaseModel):
    url: str = Field(
        default="",
        description="Proxy URL (http://host:port or socks5://host:port). Empty string disables proxy.",
    )


@router.post("/proxy", tags=["settings"])
async def update_proxy(body: ProxyUpdate):
    """Update the HTTP proxy for all outbound calls at runtime.

    This sets HTTP_PROXY / HTTPS_PROXY in the process environment and
    clears cached HTTP clients so they pick up the new proxy on next use.
    No restart required.
    """
    from main import apply_proxy

    apply_proxy(body.url)

    # Clear cached HTTP clients so they rebuild with the new proxy
    try:
        from pipeline.embedder import clear_embed_client
        clear_embed_client()
    except Exception:
        pass

    # Clear embedding cache
    try:
        from pipeline.embedder import _embed_cache
        _embed_cache.clear()
    except Exception:
        pass

    return {"proxy": body.url or None, "updated": True}


@router.get("/proxy", tags=["settings"])
async def get_proxy():
    """Return the current proxy setting."""
    import os
    return {"proxy": os.environ.get("HTTP_PROXY") or os.environ.get("ALL_PROXY") or None}


class SystemPromptUpdate(BaseModel):
    prompt: str = Field(default="", description="RAG system prompt for chat and ask_kb.")


@router.get("/system-prompt", tags=["settings"])
async def get_system_prompt():
    """Return the current RAG system prompt."""
    from api.chat import get_rag_system_prompt
    return {"prompt": get_rag_system_prompt()}


@router.post("/system-prompt", tags=["settings"])
async def update_system_prompt(body: SystemPromptUpdate):
    """Update the RAG system prompt at runtime (no restart needed)."""
    from api.chat import set_rag_system_prompt
    prompt = body.prompt.strip()
    if not prompt:
        from config import settings
        prompt = settings.rag_system_prompt
    set_rag_system_prompt(prompt)
    return {"prompt": prompt, "updated": True}


class LLMSettingsUpdate(BaseModel):
    provider: Literal["openai", "anthropic", "ollama", "custom"] = "custom"
    model: str = Field(default="", description="Default model id.")
    base_url: str = Field(default="", description="Provider base URL when applicable.")
    api_key: str = Field(default="", description="Provider API key. Empty string clears it.")


def _read_runtime_llm_settings() -> dict:
    from config import settings

    provider = settings.llm_provider
    if provider == "anthropic":
        api_key = settings.anthropic_api_key
        base_url = ""
    elif provider == "ollama":
        api_key = ""
        base_url = settings.ollama_base_url or settings.llm_base_url
    else:
        api_key = settings.llm_api_key or settings.openai_api_key
        base_url = settings.llm_base_url

    return {
        "provider": provider,
        "model": settings.llm_model,
        "base_url": base_url,
        "api_key": api_key,
    }


@router.get("/llm", tags=["settings"])
async def get_llm_settings():
    """Return the current runtime LLM configuration.

    This reflects the live in-process values used by future requests.
    """
    return _read_runtime_llm_settings()


@router.post("/llm", tags=["settings"])
async def update_llm_settings(body: LLMSettingsUpdate):
    """Update runtime LLM configuration for future requests.

    The frontend persists a browser-local copy and replays it after backend restarts;
    this endpoint is responsible for the live process state only.
    """
    from config import settings

    provider = body.provider
    model = body.model.strip() or settings.llm_model
    base_url = body.base_url.strip()
    api_key = body.api_key.strip()

    settings.llm_provider = provider
    settings.llm_model = model

    if provider == "anthropic":
        settings.anthropic_api_key = api_key
    elif provider == "ollama":
        resolved_base_url = base_url or settings.ollama_base_url or "http://localhost:11434"
        settings.ollama_base_url = resolved_base_url
        settings.llm_base_url = resolved_base_url
        settings.llm_api_key = ""
    else:
        settings.llm_base_url = base_url
        settings.llm_api_key = api_key
        if provider == "openai":
            settings.openai_api_key = api_key

    return {**_read_runtime_llm_settings(), "updated": True}


# ── Local model download ────────────────────────────────────────

@router.get("/models/status", tags=["settings"])
async def get_model_status():
    """Return download status of local models (BM25 sparse embedder and reranker)."""
    from pipeline.embedder import _bm25_model, _bm25_download_lock, is_bm25_cached
    from pipeline.reranker import _reranker_available, is_reranker_cached

    if _bm25_download_lock:
        bm25 = "downloading"
    elif _bm25_model is not None and _bm25_model is not False:
        bm25 = "loaded"
    elif _bm25_model is False:
        bm25 = "failed"
    elif is_bm25_cached():
        bm25 = "loaded"  # cached on disk, will lazy-load on first use
    else:
        bm25 = "not_loaded"

    if _reranker_available is True:
        reranker = "loaded"
    elif _reranker_available is False:
        reranker = "failed"
    elif is_reranker_cached():
        reranker = "loaded"  # cached on disk, will lazy-load on first use
    else:
        reranker = "not_loaded"

    return {"bm25": bm25, "reranker": reranker}


class ModelDownloadRequest(BaseModel):
    proxy: str = Field(
        default="",
        description="Proxy URL to use for this download. Applied before downloading.",
    )


@router.post("/models/download", tags=["settings"])
async def download_models(body: ModelDownloadRequest = ModelDownloadRequest()):
    """Trigger download of local models (BM25 and reranker) in the background.

    The frontend passes its proxy setting directly, so the download uses the
    same proxy the user configured — no dependency on previously-saved backend state.

    Returns immediately. Poll GET /settings/models/status for completion.
    """
    import asyncio as _asyncio

    # Apply the proxy the frontend sent before downloading
    if body.proxy:
        from main import apply_proxy
        apply_proxy(body.proxy)

    results = {"bm25": "skipped", "reranker": "skipped"}

    # BM25
    from pipeline.embedder import _bm25_model, _bm25_downloading, _bm25_bg
    if _bm25_model is not None and _bm25_model is not False:
        results["bm25"] = "already_loaded"
    else:
        _bm25_model = None
        _bm25_downloading = False
        _asyncio.get_running_loop().run_in_executor(None, _bm25_bg)
        results["bm25"] = "downloading"

    # Reranker
    from config import settings
    from pipeline.reranker import _reranker_available, _init_reranker
    if _reranker_available is True:
        results["reranker"] = "already_loaded"
    elif not settings.reranker_enabled:
        results["reranker"] = "skipped_disabled"
    else:
        if _reranker_available is False:
            _reranker_available = None  # reset so force retry works
        _asyncio.get_running_loop().run_in_executor(
            None, _init_reranker, settings.reranker_model, 20.0, True
        )
        results["reranker"] = "downloading"

    return results
