"""Runtime settings — proxy, local model download, and live-config endpoints."""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter()
logger = logging.getLogger(__name__)

_settings_lock = asyncio.Lock()
_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"


def _persist_env(key: str, value: str) -> None:
    """Write a key=value line back to .env so settings survive restarts."""
    try:
        if not _ENV_PATH.exists():
            return
        lines = _ENV_PATH.read_text(encoding="utf-8").split("\n")
        pattern = re.compile(rf"^{re.escape(key)}\s*=")
        replaced = False
        for i, line in enumerate(lines):
            if pattern.match(line):
                lines[i] = f"{key}={value}"
                replaced = True
                break
        if not replaced:
            lines.append(f"{key}={value}")
        _ENV_PATH.write_text("\n".join(lines), encoding="utf-8")
    except Exception:
        pass  # best-effort, never break API


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


class VisionSettingsUpdate(BaseModel):
    vision_enabled: bool | None = Field(default=None, description="Enable vision (OCR + image/video description).")
    vision_model: str = Field(default="", description="Vision model id (e.g. gpt-4o-mini).")
    vision_base_url: str = Field(default="", description="Vision provider base URL.")
    vision_api_key: str = Field(default="", description="Vision provider API key. Falls back to LLM key when empty.")
    vision_frame_interval: int | None = Field(default=None, description="Video keyframe interval in seconds (0 = disable).")


class LLMSettingsUpdate(BaseModel):
    provider: str = "deepseek"
    model: str = Field(default="", description="Default model id.")
    base_url: str = Field(default="", description="Provider base URL when applicable.")
    api_key: str = Field(default="", description="Provider API key. Empty string clears it.")


def _read_runtime_llm_settings() -> dict:
    from agents.llm import normalize_provider
    from config import settings

    raw_provider = (settings.llm_provider or "").strip().lower()
    provider = normalize_provider(
        settings.llm_provider,
        model=settings.llm_model,
        base_url=settings.llm_base_url,
    )
    api_key = settings.llm_api_key
    base_url = settings.llm_base_url or (settings.ollama_base_url if raw_provider == "ollama" else "")

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
    from agents.llm import normalize_provider
    from config import settings

    provider = normalize_provider(body.provider, model=body.model, base_url=body.base_url)
    model = body.model.strip() or settings.llm_model
    base_url = body.base_url.strip()
    api_key = body.api_key.strip()

    async with _settings_lock:
        settings.llm_provider = provider
        settings.llm_model = model
        settings.llm_base_url = base_url
        settings.llm_api_key = api_key

    # Persist key to .env for crash/restart survival
    _persist_env("LLM_API_KEY", api_key)

    return {**_read_runtime_llm_settings(), "updated": True}


def _read_runtime_vision_settings() -> dict:
    from config import settings

    return {
        "vision_enabled": settings.vision_enabled,
        "vision_model": settings.vision_model,
        "vision_base_url": settings.vision_base_url,
        "vision_api_key": settings.vision_api_key,
        "vision_frame_interval": settings.vision_frame_interval,
    }


@router.get("/vision", tags=["settings"])
async def get_vision_settings():
    """Return the current runtime vision configuration."""
    return _read_runtime_vision_settings()


@router.post("/vision", tags=["settings"])
async def update_vision_settings(body: VisionSettingsUpdate):
    """Update runtime vision configuration for future requests."""
    from config import settings

    async with _settings_lock:
        if body.vision_enabled is not None:
            settings.vision_enabled = body.vision_enabled
        if body.vision_model:
            settings.vision_model = body.vision_model.strip()
        if body.vision_base_url is not None:
            settings.vision_base_url = body.vision_base_url.strip()
        if body.vision_api_key is not None:
            settings.vision_api_key = body.vision_api_key.strip()
        if body.vision_frame_interval is not None:
            settings.vision_frame_interval = body.vision_frame_interval

    # Persist vision API key to .env for crash/restart survival
    if body.vision_api_key is not None and body.vision_api_key.strip():
        _persist_env("VISION_API_KEY", body.vision_api_key.strip())

    return {**_read_runtime_vision_settings(), "updated": True}

