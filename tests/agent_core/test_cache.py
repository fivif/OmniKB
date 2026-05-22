"""Tests for backend.agent_core.cache."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.agent_core.cache import (
    CacheAdapter,
    CacheStats,
    cache_hit_rate,
    detect_provider,
    log_cache_stats,
)


# ─── detect_provider ─────────────────────────────────────────────────


@pytest.mark.xfail(reason="Anthropic support intentionally removed; see backend/agents/llm.py SUPPORTED_LLM_PROVIDERS", strict=False)
def test_detect_provider_anthropic_by_model():
    assert detect_provider("claude-sonnet-4-6") == "anthropic"
    assert detect_provider("claude-opus-4-7") == "anthropic"


def test_detect_provider_deepseek():
    assert detect_provider("deepseek-v4-pro") == "deepseek"


def test_detect_provider_openai():
    assert detect_provider("gpt-4o") == "openai"
    assert detect_provider("o3-mini") == "openai"


def test_detect_provider_siliconflow():
    assert detect_provider("Qwen/Qwen2.5-VL-72B-Instruct") == "siliconflow"


def test_detect_provider_unknown_falls_back_to_custom():
    assert detect_provider("totally-unknown") == "custom"
    assert detect_provider("") == "custom"


# ─── CacheAdapter.prepare_messages ────────────────────────────────────


@pytest.mark.xfail(reason="Anthropic support intentionally removed; see backend/agents/llm.py SUPPORTED_LLM_PROVIDERS", strict=False)
def test_anthropic_injects_cache_control_on_system():
    system, _ = CacheAdapter().prepare_messages("anthropic", "you are X", [])
    assert isinstance(system, list)
    assert system[0]["text"] == "you are X"
    assert system[0]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.xfail(reason="Anthropic support intentionally removed; see backend/agents/llm.py SUPPORTED_LLM_PROVIDERS", strict=False)
def test_anthropic_marks_last_user_message_in_prefix():
    msgs = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "ack"},
        {"role": "user", "content": "second"},
    ]
    _, prepared = CacheAdapter().prepare_messages("anthropic", "sys", msgs)
    # Last user (index 2) should be transformed to list-of-blocks with cache_control
    last = prepared[2]
    assert isinstance(last["content"], list)
    assert last["content"][-1]["cache_control"] == {"type": "ephemeral"}
    # Earlier user (idx 0) untouched
    assert prepared[0]["content"] == "first"


@pytest.mark.xfail(reason="Anthropic support intentionally removed; see backend/agents/llm.py SUPPORTED_LLM_PROVIDERS", strict=False)
def test_anthropic_no_user_message_only_marks_system():
    """Edge case: empty history. System still gets the cache mark."""
    system, prepared = CacheAdapter().prepare_messages("anthropic", "sys", [])
    assert prepared == []
    assert system[0]["cache_control"] == {"type": "ephemeral"}


def test_openai_unchanged_messages():
    msgs = [{"role": "user", "content": "hi"}]
    sys_, prepared = CacheAdapter().prepare_messages("openai", "sys-prompt", msgs)
    assert sys_ == "sys-prompt"
    assert prepared[0]["content"] == "hi"
    # Must be a copy, not the original list
    assert prepared is not msgs


def test_deepseek_unchanged_messages():
    msgs = [{"role": "user", "content": "hi"}]
    sys_, prepared = CacheAdapter().prepare_messages("deepseek", "sys", msgs)
    assert sys_ == "sys"
    assert prepared[0]["content"] == "hi"


@pytest.mark.xfail(reason="Anthropic support intentionally removed; see backend/agents/llm.py SUPPORTED_LLM_PROVIDERS", strict=False)
def test_anthropic_handles_block_list_content():
    msgs = [
        {"role": "user", "content": [
            {"type": "text", "text": "hello"},
            {"type": "text", "text": "world"},
        ]},
    ]
    _, prepared = CacheAdapter().prepare_messages("anthropic", "sys", msgs)
    blocks = prepared[0]["content"]
    # Only the LAST block gets cache_control
    assert "cache_control" not in blocks[0]
    assert blocks[-1]["cache_control"] == {"type": "ephemeral"}


# ─── extract_stats ────────────────────────────────────────────────────


@pytest.mark.xfail(reason="Anthropic support intentionally removed; see backend/agents/llm.py SUPPORTED_LLM_PROVIDERS", strict=False)
def test_extract_stats_anthropic():
    usage = {
        "input_tokens": 1000,
        "cache_read_input_tokens": 800,
        "cache_creation_input_tokens": 50,
        "output_tokens": 200,
    }
    s = CacheAdapter().extract_stats("anthropic", "claude-sonnet-4-6", usage)
    assert s.input_tokens == 1000
    assert s.cached_tokens == 800
    assert s.cache_creation_tokens == 50
    assert s.output_tokens == 200
    # hit_rate = cached / (input + creation) = 800 / 1050 ≈ 0.762
    assert 0.7 < s.hit_rate < 0.8


def test_extract_stats_openai_via_prompt_tokens_details():
    usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 100,
        "prompt_tokens_details": {"cached_tokens": 600},
    }
    s = CacheAdapter().extract_stats("openai", "gpt-4o", usage)
    assert s.input_tokens == 1000
    assert s.cached_tokens == 600
    assert s.output_tokens == 100
    assert s.cache_creation_tokens == 0


def test_extract_stats_deepseek_via_flat_field():
    usage = {
        "prompt_tokens": 800,
        "prompt_cache_hit_tokens": 500,
        "completion_tokens": 50,
    }
    s = CacheAdapter().extract_stats("deepseek", "deepseek-v4-pro", usage)
    assert s.cached_tokens == 500


def test_extract_stats_handles_none_usage():
    s = CacheAdapter().extract_stats("openai", "gpt-4o", None)
    assert s.input_tokens == 0
    assert s.cached_tokens == 0
    assert s.hit_rate == 0.0


# ─── log + aggregate ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_log_cache_stats_appends_jsonl_line(tmp_path: Path):
    log = tmp_path / "metrics.jsonl"
    s = CacheStats(provider="anthropic", model="claude", input_tokens=100, cached_tokens=80)
    await log_cache_stats(s, log_path=log)
    await log_cache_stats(s, log_path=log)
    lines = log.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    rec = json.loads(lines[0])
    assert rec["provider"] == "anthropic"
    assert rec["cached_tokens"] == 80


def test_cache_hit_rate_empty_log_returns_zeroes(tmp_path: Path):
    log = tmp_path / "missing.jsonl"
    out = cache_hit_rate(log_path=log)
    assert out["calls"] == 0
    assert out["hit_rate"] == 0.0


@pytest.mark.asyncio
async def test_cache_hit_rate_aggregates_across_records(tmp_path: Path):
    log = tmp_path / "metrics.jsonl"
    await log_cache_stats(
        CacheStats(provider="anthropic", model="c", input_tokens=1000, cached_tokens=800),
        log_path=log,
    )
    await log_cache_stats(
        CacheStats(provider="openai", model="g", input_tokens=500, cached_tokens=300),
        log_path=log,
    )
    out = cache_hit_rate(window_seconds=None, log_path=log)
    assert out["calls"] == 2
    assert out["input_tokens"] == 1500
    assert out["cached_tokens"] == 1100
    assert "anthropic" in out["by_provider"]
    assert "openai" in out["by_provider"]
    assert out["by_provider"]["anthropic"]["calls"] == 1
