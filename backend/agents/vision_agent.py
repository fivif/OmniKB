"""VisionAgent — image description and OCR via multimodal cloud LLM.

Supports DeepSeek and other OpenAI-compatible vision endpoints.

Usage
-----
    from agents.vision_agent import describe_image, is_vision_enabled

    if is_vision_enabled():
        text = await describe_image(image_bytes, mime="image/png")
"""
from __future__ import annotations

import base64
import logging
from typing import Literal

logger = logging.getLogger(__name__)

MimeType = Literal["image/png", "image/jpeg", "image/gif", "image/webp"]

_OCR_PROMPT = (
    "请提取并输出图片中的所有文字内容，保持原有格式和段落结构。"
    "如果图片是图表、示意图或无文字的插图，请用简洁的中文或英文描述其主要内容。"
    "只输出提取/描述的内容，不要添加额外说明。"
)

_FRAME_PROMPT = (
    "这是一段视频中的一帧截图。请简洁描述画面中的主要内容、场景、人物行为或关键信息。"
    "50字以内，只输出描述本身。"
)


def is_vision_enabled() -> bool:
    from config import settings
    return settings.vision_enabled


def _resolve_provider_and_model() -> tuple[str, str]:
    """Return (provider, model) for vision calls."""
    from agents.llm import normalize_provider
    from config import settings
    provider = normalize_provider(
        settings.vision_provider or settings.llm_provider,
        model=settings.vision_model,
        base_url=settings.vision_base_url or settings.llm_base_url,
    )
    model = settings.vision_model
    return provider, model


def _b64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")


async def _call_openai_compat(
    image_bytes: bytes,
    mime: MimeType,
    prompt: str,
    model: str,
    api_key: str,
    base_url: str | None,
) -> str:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage

    kwargs: dict = {"model": model, "api_key": api_key, "max_tokens": 2048}
    if base_url:
        kwargs["base_url"] = base_url

    llm = ChatOpenAI(**kwargs)
    data_url = f"data:{mime};base64,{_b64(image_bytes)}"
    msg = HumanMessage(content=[
        {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
        {"type": "text", "text": prompt},
    ])
    result = await llm.ainvoke([msg])
    return str(result.content).strip()


async def describe_image(
    image_bytes: bytes,
    mime: MimeType = "image/png",
    prompt: str = _OCR_PROMPT,
) -> str:
    """Send *image_bytes* to the configured vision LLM and return the text response.

    Raises RuntimeError if vision is not enabled or provider is unsupported.
    """
    from config import settings

    if not settings.vision_enabled:
        raise RuntimeError("Vision is not enabled. Set VISION_ENABLED=true in .env")

    provider, model = _resolve_provider_and_model()
    logger.debug("vision call: provider=%s model=%s mime=%s", provider, model, mime)

    # Resolve API key and base URL: vision-specific > provider default
    try:
        from agents.llm import resolve_base_url

        api_key = settings.vision_api_key or settings.llm_api_key
        base_url = resolve_base_url(provider, settings.vision_base_url or settings.llm_base_url)
        return await _call_openai_compat(
            image_bytes, mime, prompt, model, api_key, base_url
        )
    except Exception as exc:
        logger.warning("vision_agent.describe_image failed: %s", exc)
        raise


async def ocr_image(image_bytes: bytes, mime: MimeType = "image/png") -> str:
    """Convenience wrapper with the OCR-specific prompt."""
    return await describe_image(image_bytes, mime=mime, prompt=_OCR_PROMPT)


async def describe_frame(image_bytes: bytes, mime: MimeType = "image/jpeg") -> str:
    """Convenience wrapper with the video-frame description prompt."""
    return await describe_image(image_bytes, mime=mime, prompt=_FRAME_PROMPT)
