"""Tool primitives — declarative tool definitions and executor.

Modeled after pi-agent-core's ToolDefinition + parallel/sequential execution
strategy (see earendil-works/pi packages/agent/src/types.ts and
src/agent-loop.ts).

Key invariants:
* In ``parallel`` mode, ``ToolExecutor.execute_batch`` returns results in the
  ORIGINAL CALL ORDER, never finish order.
* If ANY tool in the batch declares ``execution_mode="sequential"``, the
  whole batch is forced sequential.
* A tool returning ``ToolResult(terminate=True)`` is preserved in the batch
  result; the agent loop is responsible for honouring that hint.
* ``before_hook`` may block a single tool by returning ``{"block": True,
  "reason": str}`` — the others in the batch still run.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

logger = logging.getLogger(__name__)


# ─── Result + Definition ──────────────────────────────────────────────

@dataclass
class ToolResult:
    """Outcome of a single tool execution.

    ``content`` is the un-truncated raw return; truncation happens later in the
    agent loop via ``agent_core.truncate.OutputAccumulator``.
    """
    content: Any = ""
    terminate: bool = False
    error: str | None = None


ExecuteFn = Callable[[dict[str, Any]], Awaitable[ToolResult]]
"""Signature: ``async def(args: dict) -> ToolResult``"""


@dataclass
class ToolDefinition:
    """Declarative tool — name, JSON schema, async execute callable."""

    name: str
    description: str
    schema: dict[str, Any]
    """JSON Schema describing the args object — passed to the LLM verbatim."""
    execute: ExecuteFn
    """Async callable invoked with the parsed args dict."""
    execution_mode: Literal["parallel", "sequential"] = "parallel"
    render_hint: dict[str, Any] | None = None
    """Optional UI rendering hints (e.g. ``{"layout": "diff"}``)."""


# ─── Hook signatures (used by ToolExecutor.execute_batch) ─────────────

BeforeToolCall = Callable[
    [str, dict[str, Any]],
    Awaitable[dict[str, Any] | None],
]
"""``async def(tool_name, args) -> {"block": bool, "reason": str} | None``"""

AfterToolCall = Callable[
    [str, dict[str, Any], ToolResult],
    Awaitable[ToolResult],
]
"""``async def(tool_name, args, result) -> ToolResult`` (may mutate)."""


# ─── Executor ─────────────────────────────────────────────────────────


@dataclass
class _PendingCall:
    """Internal struct used by execute_batch."""
    tool_call_id: str
    tool_name: str
    args: dict[str, Any]
    blocked_reason: str | None = None  # set by before_hook
    error: str | None = None


class ToolExecutor:
    """Dispatch a batch of tool calls in parallel or sequential mode.

    Construction:
        ``ToolExecutor({"search_kb": ToolDefinition(...), ...})``

    Usage:
        results = await executor.execute_batch(
            calls=[{"tool_call_id": "tc-1", "name": "search_kb", "args": {...}}],
            on_start=lambda call: emit_event(...),
            on_end=lambda call, result: emit_event(...),
            before_hook=hooks.before_tool_call,
            after_hook=hooks.after_tool_call,
        )
        # results is list[tuple[tool_call_id, ToolResult]] in input order.
    """

    def __init__(self, tools: dict[str, ToolDefinition]):
        self._tools: dict[str, ToolDefinition] = dict(tools)

    @property
    def tools(self) -> dict[str, ToolDefinition]:
        return dict(self._tools)

    def register(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool

    async def execute_batch(
        self,
        calls: list[dict[str, Any]],
        *,
        on_start: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        on_end: Callable[[dict[str, Any], ToolResult], Awaitable[None]] | None = None,
        before_hook: BeforeToolCall | None = None,
        after_hook: AfterToolCall | None = None,
    ) -> list[tuple[str, ToolResult]]:
        if not calls:
            return []

        # Step 1 — run before_hook serially, collect block decisions.
        pending: list[_PendingCall] = []
        for call in calls:
            tc = _PendingCall(
                tool_call_id=call.get("tool_call_id", ""),
                tool_name=call.get("name", ""),
                args=dict(call.get("args", {})),
            )
            tool = self._tools.get(tc.tool_name)
            if tool is None:
                tc.error = f"unknown tool: {tc.tool_name!r}"
            elif before_hook is not None:
                try:
                    decision = await before_hook(tc.tool_name, tc.args)
                except Exception as exc:
                    logger.warning("before_hook crashed for %s: %s", tc.tool_name, exc)
                    decision = None
                if isinstance(decision, dict) and decision.get("block"):
                    tc.blocked_reason = str(decision.get("reason", "blocked"))
            pending.append(tc)

        # Step 2 — decide mode: any sequential tool forces whole-batch sequential.
        any_sequential = any(
            (t := self._tools.get(p.tool_name)) is not None
            and t.execution_mode == "sequential"
            for p in pending
        )

        async def _exec_one(p: _PendingCall) -> ToolResult:
            # Synthetic results for pre-flight failures.
            if p.error is not None:
                return ToolResult(content=f"[{p.error}]", error=p.error)
            if p.blocked_reason is not None:
                return ToolResult(
                    content=f"[blocked: {p.blocked_reason}]",
                    error=f"blocked: {p.blocked_reason}",
                )

            tool = self._tools[p.tool_name]
            if on_start is not None:
                try:
                    await on_start({
                        "tool_call_id": p.tool_call_id,
                        "tool_name": p.tool_name,
                        "args": p.args,
                    })
                except Exception as exc:
                    logger.debug("on_start crashed: %s", exc)

            try:
                result = await tool.execute(p.args)
                if not isinstance(result, ToolResult):
                    # Be forgiving: wrap raw return as content.
                    result = ToolResult(content=result)
            except Exception as exc:
                logger.warning("tool %s raised: %s", p.tool_name, exc)
                result = ToolResult(content=f"[{p.tool_name} error: {exc}]", error=str(exc))

            if after_hook is not None:
                try:
                    result = await after_hook(p.tool_name, p.args, result)
                except Exception as exc:
                    logger.warning("after_hook crashed for %s: %s", p.tool_name, exc)

            if on_end is not None:
                try:
                    await on_end(
                        {
                            "tool_call_id": p.tool_call_id,
                            "tool_name": p.tool_name,
                            "args": p.args,
                        },
                        result,
                    )
                except Exception as exc:
                    logger.debug("on_end crashed: %s", exc)

            return result

        # Step 3 — execute.
        if any_sequential or len(pending) == 1:
            results: list[ToolResult] = []
            for p in pending:
                results.append(await _exec_one(p))
        else:
            # Parallel: launch all, but preserve input order via gather.
            results = list(await asyncio.gather(*(_exec_one(p) for p in pending)))

        return [(p.tool_call_id, r) for p, r in zip(pending, results)]
