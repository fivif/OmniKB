"""Central LLM factory with DeepSeek-Reasoner thinking-mode round-trip.

Two monkey-patches to langchain-openai that together complete the circle:

1. ``_convert_dict_to_message`` (response parsing):
   → captures ``reasoning_content`` from the API response into
     ``additional_kwargs["reasoning_content"]``, where langchain stores it
     naturally on the AIMessage.

2. ``_convert_message_to_dict`` (request serialization):
   → includes ``additional_kwargs["reasoning_content"]`` in the outgoing wire
     format when present, so the provider sees its own thinking echoed back.

Without #1, ``reasoning_content`` is silently dropped on the way IN and
nothing is available for #2 to serialize on the way OUT.

Optional: ``LLM_EXTRA_BODY`` for providers that expose a flag to disable
thinking entirely (e.g. ``{"enable_thinking": false}`` for SiliconFlow Qwen).
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


# ── Dual patch ──────────────────────────────────────────────────

_PATCHED = False


def _install_reasoning_patches() -> None:
    """Monkey-patch langchain-openai's response parsing AND request serialization
    so that ``reasoning_content`` survives the round-trip."""
    global _PATCHED
    if _PATCHED:
        return

    try:
        from langchain_openai.chat_models import base as _base
    except ImportError:
        return

    # ── ① Response parsing ─────────────────────────────────────
    _orig_parse = _base._convert_dict_to_message

    def _patched_parse(_dict, *args, **kwargs):
        msg = _orig_parse(_dict, *args, **kwargs)
        # Only alter AIMessage instances
        if getattr(msg, "type", None) != "ai":
            return msg
        rc = _dict.get("reasoning_content") or _dict.get("reasoning_details")
        if rc is None:
            return msg
        ak = getattr(msg, "additional_kwargs", None)
        if ak is None:
            ak = {}
            try:
                msg.additional_kwargs = ak
            except Exception:
                return msg
        if "reasoning_content" not in ak:
            ak["reasoning_content"] = rc
        return msg

    _base._convert_dict_to_message = _patched_parse

    # ── ② Request serialization ────────────────────────────────
    _orig_serial = _base._convert_message_to_dict

    def _patched_serial(message, *args, **kwargs):
        d = _orig_serial(message, *args, **kwargs)
        if getattr(message, "type", None) != "ai":
            return d
        ak = getattr(message, "additional_kwargs", None) or {}
        rc = ak.get("reasoning_content")
        if rc and "reasoning_content" not in d:
            d["reasoning_content"] = rc
        return d

    _base._convert_message_to_dict = _patched_serial
    _PATCHED = True
    logger.info("langchain-openai: reasoning_content round-trip patched (parse + serialize)")


def preserve_reasoning(messages):
    """Safety net: copy reasoning_content from response_metadata to additional_kwargs.

    With the two patches above, this should rarely be needed — the parse patch
    already puts reasoning_content in additional_kwargs on the way in.
    Kept as a belt-and-suspenders measure.
    """
    try:
        from langchain_core.messages import AIMessage
    except ImportError:
        return messages
    for m in messages:
        if not isinstance(m, AIMessage):
            continue
        rm = getattr(m, "response_metadata", None) or {}
        rc = rm.get("reasoning_content")
        if not rc:
            continue
        ak = m.additional_kwargs
        if not isinstance(ak, dict):
            ak = {}
            try:
                m.additional_kwargs = ak
            except Exception:
                continue
        if "reasoning_content" not in ak:
            ak["reasoning_content"] = rc
    return messages


# ── Extra body ──────────────────────────────────────────────────

def _parse_extra_body() -> dict:
    from config import settings
    raw = getattr(settings, "llm_extra_body_json", "") or ""
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        logger.warning("LLM_EXTRA_BODY must be a JSON object, got %s", type(data).__name__)
    except Exception as exc:
        logger.warning("LLM_EXTRA_BODY parse failed: %s", exc)
    return {}


# ── LLM factory ─────────────────────────────────────────────────

def get_llm(temperature: float = 0, max_tokens: int | None = None):
    """Build the LLM client. Installs reasoning_content patches for OpenAI-compatible providers."""
    from config import settings

    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        kwargs: dict[str, Any] = {
            "model": settings.llm_model,
            "api_key": settings.anthropic_api_key,
            "temperature": temperature,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        return ChatAnthropic(**kwargs)

    if settings.llm_provider == "ollama":
        from langchain_ollama import ChatOllama
        kwargs: dict[str, Any] = {
            "model": settings.llm_model,
            "base_url": settings.ollama_base_url,
            "temperature": temperature,
        }
        if max_tokens:
            kwargs["num_predict"] = max_tokens
        return ChatOllama(**kwargs)

    _install_reasoning_patches()

    from langchain_openai import ChatOpenAI
    kwargs = {
        "model": settings.llm_model,
        "api_key": settings.llm_api_key or settings.openai_api_key or "none",
        "base_url": settings.llm_base_url or None,
        "temperature": temperature,
    }
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    extra_body = _parse_extra_body()
    if extra_body:
        kwargs["extra_body"] = extra_body
    return ChatOpenAI(**kwargs)


# Backward-compat shim
def strip_reasoning(messages):
    """Deprecated alias. Does the same as preserve_reasoning now."""
    return preserve_reasoning(messages)
