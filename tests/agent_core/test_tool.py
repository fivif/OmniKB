"""Tests for backend.agent_core.tool — ToolExecutor parallel / sequential / hooks."""
from __future__ import annotations

import asyncio

import pytest

from backend.agent_core.tool import (
    ToolDefinition,
    ToolExecutor,
    ToolResult,
)

# ─── Helpers ─────────────────────────────────────────────────────────


def _make_tool(
    name: str,
    *,
    delay: float = 0.0,
    payload: str | None = None,
    execution_mode: str = "parallel",
    raise_exc: Exception | None = None,
    terminate: bool = False,
):
    async def _execute(args):
        if delay:
            await asyncio.sleep(delay)
        if raise_exc is not None:
            raise raise_exc
        return ToolResult(content=payload if payload is not None else f"{name}:{args}", terminate=terminate)
    return ToolDefinition(
        name=name,
        description=f"test tool {name}",
        schema={"type": "object", "properties": {}},
        execute=_execute,
        execution_mode=execution_mode,
    )


# ─── Test cases ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parallel_preserves_order():
    """Slow tool first, fast tool second — results MUST be in input order."""
    slow = _make_tool("slow", delay=0.05, payload="S")
    fast = _make_tool("fast", delay=0.001, payload="F")
    ex = ToolExecutor({"slow": slow, "fast": fast})
    results = await ex.execute_batch([
        {"tool_call_id": "1", "name": "slow", "args": {}},
        {"tool_call_id": "2", "name": "fast", "args": {}},
    ])
    assert [tc for tc, _ in results] == ["1", "2"]
    assert results[0][1].content == "S"
    assert results[1][1].content == "F"


@pytest.mark.asyncio
async def test_sequential_mode_forced_when_any_tool_marked():
    """If any tool declares sequential, the whole batch must run sequentially."""
    order: list[str] = []

    async def _exec_a(_):
        order.append("a-start")
        await asyncio.sleep(0.02)
        order.append("a-end")
        return ToolResult(content="a")

    async def _exec_b(_):
        order.append("b-start")
        order.append("b-end")
        return ToolResult(content="b")

    a = ToolDefinition(name="a", description="", schema={}, execute=_exec_a, execution_mode="sequential")
    b = ToolDefinition(name="b", description="", schema={}, execute=_exec_b, execution_mode="parallel")
    ex = ToolExecutor({"a": a, "b": b})
    await ex.execute_batch([
        {"tool_call_id": "1", "name": "a", "args": {}},
        {"tool_call_id": "2", "name": "b", "args": {}},
    ])
    # Sequential: a fully completes before b starts.
    assert order == ["a-start", "a-end", "b-start", "b-end"]


@pytest.mark.asyncio
async def test_terminate_hint_preserved():
    t = _make_tool("t", payload="done", terminate=True)
    ex = ToolExecutor({"t": t})
    results = await ex.execute_batch([
        {"tool_call_id": "1", "name": "t", "args": {}}
    ])
    assert results[0][1].terminate is True


@pytest.mark.asyncio
async def test_before_hook_blocks_one_keeps_others():
    """before_hook returns block on tool 'a'; tool 'b' should still run."""
    a = _make_tool("a", payload="A")
    b = _make_tool("b", payload="B")
    ex = ToolExecutor({"a": a, "b": b})

    async def block_a(name, args):
        if name == "a":
            return {"block": True, "reason": "policy"}
        return None

    results = await ex.execute_batch(
        [
            {"tool_call_id": "1", "name": "a", "args": {}},
            {"tool_call_id": "2", "name": "b", "args": {}},
        ],
        before_hook=block_a,
    )
    assert results[0][1].error is not None
    assert "policy" in results[0][1].error
    assert results[1][1].content == "B"


@pytest.mark.asyncio
async def test_unknown_tool_returns_synthetic_error():
    ex = ToolExecutor({})
    results = await ex.execute_batch([
        {"tool_call_id": "1", "name": "no-such-tool", "args": {}}
    ])
    assert results[0][1].error is not None
    assert "unknown" in results[0][1].error


@pytest.mark.asyncio
async def test_exception_becomes_tool_result_error():
    bad = _make_tool("bad", raise_exc=RuntimeError("boom"))
    ex = ToolExecutor({"bad": bad})
    results = await ex.execute_batch([
        {"tool_call_id": "1", "name": "bad", "args": {}}
    ])
    assert results[0][1].error is not None
    assert "boom" in results[0][1].error
    # Original input order maintained even after exception
    assert results[0][0] == "1"


@pytest.mark.asyncio
async def test_after_hook_can_mutate_result():
    t = _make_tool("t", payload="raw")
    ex = ToolExecutor({"t": t})

    async def post(name, args, result):
        return ToolResult(content=result.content + "+after", terminate=result.terminate)

    results = await ex.execute_batch(
        [{"tool_call_id": "1", "name": "t", "args": {}}],
        after_hook=post,
    )
    assert results[0][1].content == "raw+after"


@pytest.mark.asyncio
async def test_on_start_on_end_callbacks_fired():
    t = _make_tool("t", payload="x")
    ex = ToolExecutor({"t": t})

    started: list[str] = []
    ended: list[str] = []

    async def on_start(call):
        started.append(call["tool_call_id"])

    async def on_end(call, result):
        ended.append(call["tool_call_id"])

    await ex.execute_batch(
        [{"tool_call_id": "1", "name": "t", "args": {}}],
        on_start=on_start,
        on_end=on_end,
    )
    assert started == ["1"]
    assert ended == ["1"]


@pytest.mark.asyncio
async def test_empty_batch_returns_empty():
    ex = ToolExecutor({})
    assert await ex.execute_batch([]) == []
