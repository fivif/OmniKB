"""Tests for backend.agent_core.tokens."""
from __future__ import annotations

from backend.agent_core.tokens import (
    context_window,
    count_messages_tokens,
    count_tokens,
)
from backend.agent_core.messages import (
    AssistantMessage,
    ToolMessage,
    UserMessage,
)


# ─── count_tokens ─────────────────────────────────────────────────────

def test_count_tokens_empty_returns_zero():
    assert count_tokens("", "gpt-4o") == 0


def test_count_tokens_english():
    """A short English phrase should be 2-5 tokens — anything in that range."""
    n = count_tokens("hello world", "gpt-4o")
    assert 1 <= n <= 6


def test_count_tokens_chinese_estimate():
    """100 Chinese characters should produce a non-trivial count.

    cl100k_base under-counts Chinese; we just want >= 30 (sanity check).
    """
    text = "中" * 100
    n = count_tokens(text, "deepseek-v4-pro")
    assert n >= 30


def test_count_tokens_anthropic_uses_heuristic():
    """Anthropic models go through the heuristic path; ensure non-zero."""
    n = count_tokens("hello world", "claude-sonnet-4-6")
    assert n >= 1


# ─── context_window ────────────────────────────────────────────────────

def test_context_window_known_models():
    assert context_window("deepseek-v4-pro") == 131072
    assert context_window("claude-sonnet-4-6") == 200000
    assert context_window("claude-opus-4-7") == 200000
    assert context_window("gpt-4o") == 128000


def test_context_window_case_insensitive_and_prefix():
    assert context_window("DeepSeek-V4-Pro") == 131072
    assert context_window("claude-sonnet-4-6-20260101") == 200000


def test_context_window_unknown_returns_safe_default():
    assert context_window("totally-made-up-model") == 32768
    assert context_window("") == 32768


# ─── count_messages_tokens ─────────────────────────────────────────────

def test_count_messages_tokens_includes_overhead():
    msgs = [
        UserMessage(content="hello"),
        AssistantMessage(content="hi there"),
    ]
    n = count_messages_tokens(msgs, "gpt-4o")
    # At least 4*2 overhead + a few content tokens
    assert n >= 8


def test_count_messages_tokens_includes_tool_calls():
    msgs = [
        AssistantMessage(
            content="",
            tool_calls=[{"tool_call_id": "x", "name": "search_kb", "args": {"q": "deep learning research"}}],
        ),
    ]
    n = count_messages_tokens(msgs, "gpt-4o")
    assert n >= 5


def test_count_messages_tokens_handles_tool_message():
    msgs = [
        ToolMessage(tool_call_id="x", tool_name="search", content="some result"),
    ]
    n = count_messages_tokens(msgs, "gpt-4o")
    assert n >= 4


def test_count_messages_tokens_empty_list():
    assert count_messages_tokens([], "gpt-4o") == 0
