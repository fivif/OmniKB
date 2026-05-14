"""BudgetTracker — runtime guardrails for an agent run.

Caps that ``run_loop`` honours when a ``BudgetTracker`` is attached:

* **max_input_tokens / max_output_tokens** — accumulated across all turns;
  measured against the provider's ``usage_metadata`` (Anthropic + OpenAI
  shape supported via the cache adapter).
* **max_seconds** — wall-clock from ``start()`` to current ``check_*`` call.
* **max_total_tool_calls** — total tool invocations across the run.
* **per_tool_max_calls** — dict of per-tool caps. Lookup by tool name; a
  missing key means unlimited.

Each ``check_*`` returns ``None`` when within budget, otherwise a string
reason that the loop bubbles up via ``agent_end.final_status="budget_exceeded"``
and ``agent_end.data.budget_reason``.

Designed to be construction-cheap (a dataclass with primitive counters) so
agents can opt-in by simply passing a ``BudgetTracker`` to ``run_loop``.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class BudgetTracker:
    """Soft caps on tokens / time / tool-call counts for a single agent run.

    Any field set to ``None`` is treated as "unlimited". Counters mutate
    in-place; the loop reads them between turns and tool invocations.
    """

    # Caps
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_seconds: float | None = None
    max_total_tool_calls: int | None = None
    per_tool_max_calls: dict[str, int] = field(default_factory=dict)

    # Counters (mutated by run_loop)
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    total_tool_calls: int = 0
    tool_call_counts: dict[str, int] = field(default_factory=dict)
    _start: float = 0.0

    def start(self) -> None:
        """Reset wall-clock start. Called once at run_loop entry."""
        self._start = time.monotonic()

    # ── Counter updates ──────────────────────────────────────────────

    def tick_usage(self, *, input_tokens: int = 0, output_tokens: int = 0, cached_tokens: int = 0) -> None:
        self.input_tokens += max(int(input_tokens or 0), 0)
        self.output_tokens += max(int(output_tokens or 0), 0)
        self.cached_tokens += max(int(cached_tokens or 0), 0)

    def tick_tool_call(self, tool_name: str) -> None:
        self.total_tool_calls += 1
        self.tool_call_counts[tool_name] = self.tool_call_counts.get(tool_name, 0) + 1

    # ── Check helpers ────────────────────────────────────────────────

    def elapsed_seconds(self) -> float:
        if self._start == 0.0:
            return 0.0
        return time.monotonic() - self._start

    def check_pre_llm(self) -> str | None:
        """Return a reason if the loop should stop BEFORE the next LLM call."""
        if self.max_seconds is not None and self.elapsed_seconds() > self.max_seconds:
            return f"wall-clock budget exceeded ({self.elapsed_seconds():.1f}s > {self.max_seconds}s)"
        if self.max_input_tokens is not None and self.input_tokens > self.max_input_tokens:
            return f"input token budget exceeded ({self.input_tokens} > {self.max_input_tokens})"
        if self.max_output_tokens is not None and self.output_tokens > self.max_output_tokens:
            return f"output token budget exceeded ({self.output_tokens} > {self.max_output_tokens})"
        if self.max_total_tool_calls is not None and self.total_tool_calls >= self.max_total_tool_calls:
            return f"total tool-call budget reached ({self.total_tool_calls} >= {self.max_total_tool_calls})"
        return None

    def check_pre_tool(self, tool_name: str) -> str | None:
        """Return a reason if this specific tool call should be blocked."""
        cap = self.per_tool_max_calls.get(tool_name)
        if cap is None:
            return None
        cur = self.tool_call_counts.get(tool_name, 0)
        if cur >= cap:
            return f"tool {tool_name!r} hit per-tool cap ({cur} >= {cap})"
        return None

    # ── Reporting ────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        """JSON-friendly snapshot for inclusion in agent_end events."""
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "total_tool_calls": self.total_tool_calls,
            "tool_call_counts": dict(self.tool_call_counts),
            "elapsed_seconds": round(self.elapsed_seconds(), 3),
            "caps": {
                "max_input_tokens": self.max_input_tokens,
                "max_output_tokens": self.max_output_tokens,
                "max_seconds": self.max_seconds,
                "max_total_tool_calls": self.max_total_tool_calls,
                "per_tool_max_calls": dict(self.per_tool_max_calls),
            },
        }
