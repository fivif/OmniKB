"""Token counting for OmniKB Agent Core.

Two responsibilities:
1. ``count_tokens(text, model)`` — best-effort tokenisation of a string
2. ``count_messages_tokens(messages, model)`` — total tokens of a transcript
3. ``context_window(model)`` — hardcoded ctx-window table per provider

For OpenAI / DeepSeek / SiliconFlow we use ``tiktoken`` with ``cl100k_base``;
DeepSeek / Qwen don't ship official tokenisers, ``cl100k_base`` is a known
under-estimate for Chinese (~10-15 % low). The agent loop uses
``reserve_tokens=4096`` precisely to absorb that miscounting.

For Anthropic we try the SDK's ``client.messages.count_tokens()`` if the
package is installed; otherwise fall back to a simple heuristic.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .messages import AgentMessage

logger = logging.getLogger(__name__)


# ─── Model → ctx window (hard-coded; updated 2026-05) ────────────────
# Keys are matched case-insensitively via ``_match_model``; first prefix wins.
_CONTEXT_WINDOWS: dict[str, int] = {
    # DeepSeek
    "deepseek-v4-pro": 131072,
    "deepseek-v4-flash": 131072,
    "deepseek-v4": 131072,
    "deepseek-v3": 131072,
    "deepseek-r1": 65536,
    "deepseek-coder": 131072,
    "deepseek-reasoner": 65536,
    # Anthropic
    "claude-opus-4-7": 200000,
    "claude-sonnet-4-6": 200000,
    "claude-sonnet-4": 200000,
    "claude-opus-4": 200000,
    "claude-haiku-4": 200000,
    "claude-3-5-sonnet": 200000,
    "claude-3-5-haiku": 200000,
    "claude-3-opus": 200000,
    "claude-3-haiku": 200000,
    # OpenAI
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4-turbo": 128000,
    "gpt-4": 8192,
    "gpt-3.5-turbo": 16384,
    "o1": 200000,
    "o3": 200000,
    "o4-mini": 200000,
    # Qwen / SiliconFlow common
    "qwen3": 131072,
    "qwen2.5": 131072,
    "qwen2": 32768,
    # BAAI Bge isn't an LLM, but for safety
    "bge-m3": 8192,
}

# Default fallback when model is unknown
_DEFAULT_CONTEXT_WINDOW = 32768

# Token overhead per message (heuristic, mirrors OpenAI's "every message follows
# <|start|>{role/name}\n{content}<|end|>\n" framing — about 4 tokens of frame
# tokens per message).
_PER_MESSAGE_OVERHEAD = 4

# When we can't tokenise (no tiktoken, unknown encoding) we estimate as:
#   len(text) / _CHARS_PER_TOKEN
# The constant is conservative for mixed Chinese + English: 1 Chinese char
# averages ~1.5 cl100k tokens, 1 English token averages ~4 chars, so ~3-3.5
# is a safe middle.
_CHARS_PER_TOKEN = 3.0


# ─── Internal helpers ─────────────────────────────────────────────────

def _match_model(model: str) -> str | None:
    """Return the matching key in ``_CONTEXT_WINDOWS`` (case-insensitive prefix)."""
    if not model:
        return None
    name = model.lower().strip()
    # Exact match first
    if name in _CONTEXT_WINDOWS:
        return name
    # Prefix / contains match — try longest prefix first
    for key in sorted(_CONTEXT_WINDOWS.keys(), key=len, reverse=True):
        if name.startswith(key) or key in name:
            return key
    return None


def _is_anthropic(model: str) -> bool:
    return "claude" in (model or "").lower()


def _heuristic_count(text: str) -> int:
    if not text:
        return 0
    return max(1, int(round(len(text) / _CHARS_PER_TOKEN)))


_tiktoken_encoder = None  # cached tiktoken encoder (cl100k_base)


def _get_tiktoken():
    """Return a cached cl100k_base encoder, or None if tiktoken unavailable."""
    global _tiktoken_encoder
    if _tiktoken_encoder is False:  # negative cache
        return None
    if _tiktoken_encoder is not None:
        return _tiktoken_encoder
    try:
        import tiktoken  # type: ignore
        _tiktoken_encoder = tiktoken.get_encoding("cl100k_base")
        return _tiktoken_encoder
    except Exception as exc:
        logger.debug("tiktoken unavailable, falling back to heuristic: %s", exc)
        _tiktoken_encoder = False  # type: ignore[assignment]
        return None


# ─── Public API ───────────────────────────────────────────────────────

def context_window(model: str) -> int:
    """Return the LLM's max context window in tokens.

    Returns a safe default (32 768) for unknown models.
    """
    key = _match_model(model)
    if key is None:
        return _DEFAULT_CONTEXT_WINDOW
    return _CONTEXT_WINDOWS[key]


def count_tokens(text: str, model: str) -> int:
    """Estimate the token count of ``text`` under ``model``'s tokeniser.

    Uses tiktoken cl100k_base for OpenAI/DeepSeek/Qwen/SiliconFlow.
    Uses a char/3 heuristic otherwise (Anthropic without SDK, unknown providers).
    """
    if not text:
        return 0
    if _is_anthropic(model):
        # Anthropic SDK call would be precise but synchronous-network; for
        # tight loops we prefer the heuristic. Real Anthropic count happens
        # via the SDK in cache.py when needed.
        return _heuristic_count(text)
    enc = _get_tiktoken()
    if enc is None:
        return _heuristic_count(text)
    try:
        return len(enc.encode(text))
    except Exception:
        return _heuristic_count(text)


def count_messages_tokens(messages: "list[AgentMessage]", model: str) -> int:
    """Sum tokens across an AgentMessage list with per-message framing overhead."""
    total = 0
    for m in messages:
        # We sum content + tool_calls + thinking when present
        content = getattr(m, "content", "") or ""
        total += count_tokens(content, model)
        # Tool calls (assistant)
        tool_calls = getattr(m, "tool_calls", None)
        if tool_calls:
            for tc in tool_calls:
                name = tc.get("name", "")
                args = str(tc.get("args", ""))
                total += count_tokens(name + " " + args, model)
        thinking = getattr(m, "thinking", None)
        if thinking:
            total += count_tokens(thinking, model)
        # tool_name on ToolMessage
        tn = getattr(m, "tool_name", None)
        if tn:
            total += count_tokens(tn, model)
        total += _PER_MESSAGE_OVERHEAD
    return total
