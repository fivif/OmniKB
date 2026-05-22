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

DEEPSEEK_API_BASE = "https://api.deepseek.com/v1"
SUPPORTED_LLM_PROVIDERS = {"deepseek", "custom"}

# Provider values we silently coerce to "custom". The first time a user hits
# one of these we emit a one-shot warning so the env-file drift is visible.
_LEGACY_PROVIDER_VALUES = frozenset({"openai", "anthropic", "claude", "ollama"})
_warned_legacy_providers: set[str] = set()


def _warn_legacy_provider_once(value: str) -> None:
    if value in _warned_legacy_providers:
        return
    _warned_legacy_providers.add(value)
    logger.warning(
        "LLM_PROVIDER=%r is treated as 'custom' (OpenAI-compatible). "
        "Native Anthropic / Ollama protocols are NOT implemented; only the "
        "OpenAI wire format is supported. Update LLM_PROVIDER to 'deepseek' "
        "or 'custom' to silence this warning.",
        value,
    )


def normalize_provider(
    provider: str | None,
    *,
    model: str = "",
    base_url: str = "",
) -> str:
    """Collapse legacy provider values into the current supported set."""
    value = (provider or "").strip().lower()
    if value in SUPPORTED_LLM_PROVIDERS:
        return value
    if value in _LEGACY_PROVIDER_VALUES:
        _warn_legacy_provider_once(value)
        return "custom"

    model_hint = (model or "").strip().lower()
    base_hint = (base_url or "").strip().lower()
    if "deepseek" in model_hint or "deepseek" in base_hint:
        return "deepseek"
    if value or base_hint:
        return "custom"
    return "deepseek"


def resolve_base_url(provider: str, base_url: str = "") -> str | None:
    normalized = normalize_provider(provider, base_url=base_url)
    raw = (base_url or "").strip()
    if normalized == "deepseek":
        return raw or DEEPSEEK_API_BASE
    if normalized == "custom":
        return raw or None
    return None


# ── Reasoning round-trip via subclass override ──────────────────
#
# Earlier we monkey-patched langchain_openai.chat_models.base's two private
# functions ``_convert_dict_to_message`` and ``_convert_message_to_dict`` to
# preserve DeepSeek's ``reasoning_content`` field across the wire.
#
# That worked but was fragile: ANY private symbol rename in a langchain-openai
# patch release would silently lose thinking-mode context. The subclass
# approach below uses two PUBLIC override hooks (``_create_chat_result`` and
# ``_get_request_payload``) that have been part of the BaseChatOpenAI API for
# many releases and are far less likely to disappear without notice.
#
# A langchain-openai version that drops these hooks would fail at startup with
# a clear AttributeError instead of silently losing reasoning context — exactly
# the failure mode we want.

_subclass_cache: type | None = None


def _get_omni_chat_class():
    """Return the lazily-built ``OmniChatOpenAI`` subclass.

    Built on first call so importing this module doesn't drag langchain
    in unnecessarily (e.g. for ``normalize_provider`` callers that don't
    actually need an LLM client).
    """
    global _subclass_cache
    if _subclass_cache is not None:
        return _subclass_cache

    from langchain_core.messages import AIMessage
    from langchain_openai import ChatOpenAI

    class OmniChatOpenAI(ChatOpenAI):  # type: ignore[misc]
        """ChatOpenAI variant that round-trips DeepSeek ``reasoning_content``.

        Override points (both public hooks of BaseChatOpenAI):

        - :meth:`_create_chat_result` runs after the SDK parses an OpenAI
          response. We re-read the raw response dict to grab
          ``reasoning_content`` (which the default parser drops) and stash it
          into the AIMessage's ``additional_kwargs``.
        - :meth:`_get_request_payload` runs before the request hits the wire.
          We re-inject any AIMessage's ``additional_kwargs.reasoning_content``
          back into its serialised dict so DeepSeek sees its own thinking
          echoed in conversation history.
        """

        def _create_chat_result(self, response, generation_info=None):
            result = super()._create_chat_result(response, generation_info)
            try:
                response_dict = (
                    response
                    if isinstance(response, dict)
                    else response.model_dump(
                        exclude={"choices": {"__all__": {"message": {"parsed"}}}}
                    )
                )
                choices = response_dict.get("choices") or []
                for gen, res in zip(result.generations, choices):
                    message = getattr(gen, "message", None)
                    if not isinstance(message, AIMessage):
                        continue
                    raw_msg = res.get("message") if isinstance(res, dict) else None
                    if not isinstance(raw_msg, dict):
                        continue
                    rc = raw_msg.get("reasoning_content") or raw_msg.get("reasoning_details")
                    if rc is None:
                        continue
                    ak = getattr(message, "additional_kwargs", None) or {}
                    if "reasoning_content" not in ak:
                        ak["reasoning_content"] = rc
                        try:
                            message.additional_kwargs = ak
                        except Exception:  # noqa: BLE001
                            pass
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "OmniChatOpenAI: response post-process failed (non-fatal): %s",
                    exc,
                )
            return result

        def _get_request_payload(self, input_, *, stop=None, **kwargs):
            payload = super()._get_request_payload(input_, stop=stop, **kwargs)
            try:
                msgs_in = self._convert_input(input_).to_messages()
                msgs_out = payload.get("messages")
                if isinstance(msgs_out, list) and len(msgs_out) == len(msgs_in):
                    for src, dst in zip(msgs_in, msgs_out):
                        if not isinstance(src, AIMessage) or not isinstance(dst, dict):
                            continue
                        ak = getattr(src, "additional_kwargs", None) or {}
                        rc = ak.get("reasoning_content")
                        if rc and "reasoning_content" not in dst:
                            dst["reasoning_content"] = rc
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "OmniChatOpenAI: request pre-process failed (non-fatal): %s",
                    exc,
                )
            return payload

    _subclass_cache = OmniChatOpenAI
    logger.info(
        "agents.llm: using OmniChatOpenAI subclass for reasoning_content round-trip"
    )
    return _subclass_cache


def preserve_reasoning(messages):
    """Safety net: copy reasoning_content from response_metadata to additional_kwargs.

    With :class:`OmniChatOpenAI` in use this is rarely needed — the response
    hook already drops ``reasoning_content`` straight into ``additional_kwargs``
    on the way in. Kept as a belt-and-suspenders helper for callers that work
    with langchain messages produced outside our subclass (e.g. cached
    serialised messages, third-party tools).
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


def build_chat_model(
    provider: str | None,
    model: str,
    *,
    api_key: str = "",
    base_url: str = "",
    temperature: float = 0,
    max_tokens: int | None = None,
    streaming: bool = False,
):
    """Build a chat model for DeepSeek or generic compatible providers.

    Returns an :class:`OmniChatOpenAI` instance — a ChatOpenAI subclass that
    transparently round-trips DeepSeek's ``reasoning_content`` field via
    public override hooks rather than monkey-patching.
    """
    normalized = normalize_provider(provider, model=model, base_url=base_url)

    OmniChatOpenAI = _get_omni_chat_class()

    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": api_key or "none",
        "temperature": temperature,
    }
    resolved_base_url = resolve_base_url(normalized, base_url)
    if resolved_base_url:
        kwargs["base_url"] = resolved_base_url
    if streaming:
        kwargs["streaming"] = True
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    extra_body = _parse_extra_body()
    if extra_body:
        kwargs["extra_body"] = extra_body
    return OmniChatOpenAI(**kwargs)


# ── LLM factory ─────────────────────────────────────────────────

def get_llm(temperature: float = 0, max_tokens: int | None = None):
    """Build the configured LLM client for DeepSeek or custom gateways."""
    from config import settings
    provider = normalize_provider(
        settings.llm_provider,
        model=settings.llm_model,
        base_url=settings.llm_base_url,
    )
    return build_chat_model(
        provider,
        settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        temperature=temperature,
        max_tokens=max_tokens,
    )


# Backward-compat shim
def strip_reasoning(messages):
    """Deprecated alias. Does the same as preserve_reasoning now."""
    return preserve_reasoning(messages)
