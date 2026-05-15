"""Prompt-cache adapter — provider-specific cache accounting.

Current runtime providers rely on automatic prefix caching. We do
  nothing on the request side; just read ``response.usage.prompt_tokens_details.cached_tokens``
  (OpenAI) or ``response.usage.cached_tokens`` (DeepSeek) for stats.

The agent loop (M1.6) calls ``prepare_messages()`` right before sending and
``extract_stats()`` right after the response. ``log_cache_stats()`` appends
JSONL to ``data/cache_metrics.jsonl`` and ``cache_hit_rate()`` reads the
sliding window for the ``GET /metrics/cache`` endpoint.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)


Provider = Literal["openai", "deepseek", "siliconflow", "custom"]


# ─── Provider detection ───────────────────────────────────────────────


def detect_provider(model_or_provider: str) -> Provider:
    """Heuristic: classify a model name OR a configured provider string."""
    s = (model_or_provider or "").lower()
    if "deepseek" in s:
        return "deepseek"
    if "qwen" in s or "siliconflow" in s or "bge" in s:
        return "siliconflow"
    if s.startswith("gpt") or s == "openai" or s.startswith("o1") or s.startswith("o3") or s.startswith("o4"):
        return "openai"
    return "custom"


# ─── Stats record ─────────────────────────────────────────────────────


@dataclass
class CacheStats:
    """One LLM call's cache accounting."""
    provider: Provider
    model: str
    input_tokens: int = 0
    cached_tokens: int = 0
    cache_creation_tokens: int = 0  # Anthropic-specific
    output_tokens: int = 0
    timestamp: float = field(default_factory=time.time)

    @property
    def hit_rate(self) -> float:
        total = self.input_tokens + self.cache_creation_tokens
        if total <= 0:
            return 0.0
        return self.cached_tokens / total


# ─── Adapter ──────────────────────────────────────────────────────────


_EPHEMERAL = {"type": "ephemeral"}


class CacheAdapter:
    """Stateless transformer; safe to share globally."""

    def prepare_messages(
        self,
        provider: Provider,
        system_prompt: str,
        messages: list[dict[str, Any]],
    ) -> tuple[Any, list[dict[str, Any]]]:
        """Return ``(system, messages)`` ready for providers with auto caching."""
        return system_prompt, list(messages)

    def extract_stats(
        self,
        provider: Provider,
        model: str,
        response_usage: dict[str, Any] | None,
    ) -> CacheStats:
        """Read provider-native usage fields into a uniform CacheStats."""
        u = response_usage or {}
        # OpenAI-compatible providers (DeepSeek/SiliconFlow/Qwen included)
        cached = 0
        details = u.get("prompt_tokens_details")
        if isinstance(details, dict):
            cached = int(details.get("cached_tokens", 0) or 0)
        if cached == 0:
            # DeepSeek puts it directly: usage.prompt_cache_hit_tokens
            cached = int(
                u.get("cached_tokens", 0)
                or u.get("prompt_cache_hit_tokens", 0)
                or 0
            )

        return CacheStats(
            provider=provider,
            model=model,
            input_tokens=int(u.get("prompt_tokens", 0) or u.get("input_tokens", 0) or 0),
            cached_tokens=cached,
            cache_creation_tokens=0,
            output_tokens=int(u.get("completion_tokens", 0) or u.get("output_tokens", 0) or 0),
        )


# Module-level singleton (CacheAdapter holds no mutable state)
adapter = CacheAdapter()


# ─── Persistence (jsonl log) ──────────────────────────────────────────


def _default_log_path() -> Path:
    project_root = Path(__file__).resolve().parents[2]
    return project_root / "data" / "cache_metrics.jsonl"


async def log_cache_stats(
    stats: CacheStats,
    *,
    log_path: Path | str | None = None,
) -> None:
    """Append one CacheStats record as a single JSON line."""
    target = Path(log_path) if log_path else _default_log_path()
    record = {
        "t": stats.timestamp,
        "provider": stats.provider,
        "model": stats.model,
        "input_tokens": stats.input_tokens,
        "cached_tokens": stats.cached_tokens,
        "cache_creation_tokens": stats.cache_creation_tokens,
        "output_tokens": stats.output_tokens,
    }
    line = json.dumps(record, ensure_ascii=False) + "\n"
    await asyncio.to_thread(_append, target, line)


def _append(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line)


def cache_hit_rate(
    window_seconds: int | None = 3600,
    *,
    log_path: Path | str | None = None,
) -> dict[str, Any]:
    """Aggregate stats over the last ``window_seconds`` (or all time if None).

    Returns a dict suitable for direct JSON response to ``GET /metrics/cache``.
    """
    target = Path(log_path) if log_path else _default_log_path()
    if not target.exists():
        return _empty_metrics()

    now = time.time()
    cutoff = (now - window_seconds) if window_seconds else 0.0

    total_input = 0
    total_cached = 0
    total_creation = 0
    total_output = 0
    call_count = 0
    by_provider: dict[str, dict[str, int]] = {}

    try:
        with target.open("r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if rec.get("t", 0) < cutoff:
                    continue
                call_count += 1
                total_input += int(rec.get("input_tokens", 0))
                total_cached += int(rec.get("cached_tokens", 0))
                total_creation += int(rec.get("cache_creation_tokens", 0))
                total_output += int(rec.get("output_tokens", 0))

                p = rec.get("provider", "unknown")
                bucket = by_provider.setdefault(p, {
                    "calls": 0, "input": 0, "cached": 0, "creation": 0, "output": 0,
                })
                bucket["calls"] += 1
                bucket["input"] += int(rec.get("input_tokens", 0))
                bucket["cached"] += int(rec.get("cached_tokens", 0))
                bucket["creation"] += int(rec.get("cache_creation_tokens", 0))
                bucket["output"] += int(rec.get("output_tokens", 0))
    except OSError as exc:
        logger.warning("cache_hit_rate read failed: %s", exc)
        return _empty_metrics()

    denom = total_input + total_creation
    overall_rate = (total_cached / denom) if denom > 0 else 0.0

    return {
        "window_seconds": window_seconds,
        "calls": call_count,
        "input_tokens": total_input,
        "cached_tokens": total_cached,
        "cache_creation_tokens": total_creation,
        "output_tokens": total_output,
        "hit_rate": round(overall_rate, 4),
        "by_provider": {
            p: {
                "calls": v["calls"],
                "input_tokens": v["input"],
                "cached_tokens": v["cached"],
                "cache_creation_tokens": v["creation"],
                "output_tokens": v["output"],
                "hit_rate": round(
                    (v["cached"] / (v["input"] + v["creation"]))
                    if (v["input"] + v["creation"]) > 0 else 0.0,
                    4,
                ),
            }
            for p, v in by_provider.items()
        },
    }


def _empty_metrics() -> dict[str, Any]:
    return {
        "window_seconds": None,
        "calls": 0,
        "input_tokens": 0,
        "cached_tokens": 0,
        "cache_creation_tokens": 0,
        "output_tokens": 0,
        "hit_rate": 0.0,
        "by_provider": {},
    }
