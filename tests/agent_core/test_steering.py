"""Tests for backend.agent_core.steering."""
from __future__ import annotations

import asyncio

import pytest

from backend.agent_core.steering import (
    FollowUpQueue,
    SteeringQueue,
    active_task_ids,
    clear_registry_for_tests,
    get_queues,
    register,
    unregister,
)


@pytest.fixture(autouse=True)
def _clean():
    clear_registry_for_tests()
    yield
    clear_registry_for_tests()


# ─── Queue mechanics ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_steering_push_drain_round_trip():
    q = SteeringQueue()
    n = await q.push("hello")
    assert n == 1
    assert q.peek() is True
    drained = q.drain()
    assert len(drained) == 1
    assert drained[0].content == "hello"
    assert drained[0].priority == "normal"
    assert q.peek() is False
    assert q.size == 0


@pytest.mark.asyncio
async def test_steering_interrupt_priority_sets_flag():
    q = SteeringQueue()
    await q.push("calm", priority="normal")
    assert q.is_interrupt_pending() is False
    await q.push("STOP", priority="interrupt")
    assert q.is_interrupt_pending() is True


@pytest.mark.asyncio
async def test_followup_queue_independent_from_steering():
    s = SteeringQueue()
    f = FollowUpQueue()
    await s.push("a")
    await f.push("b")
    s_msgs = s.drain()
    f_msgs = f.drain()
    assert s_msgs[0].content == "a"
    assert f_msgs[0].content == "b"


@pytest.mark.asyncio
async def test_drain_returns_in_push_order():
    q = SteeringQueue()
    await q.push("first")
    await q.push("second")
    await q.push("third")
    drained = q.drain()
    assert [m.content for m in drained] == ["first", "second", "third"]


# ─── Registry ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_returns_taskqueues():
    tq = await register("task-1")
    assert isinstance(tq.steering, SteeringQueue)
    assert isinstance(tq.follow_up, FollowUpQueue)


@pytest.mark.asyncio
async def test_register_is_idempotent():
    tq1 = await register("task-1")
    tq2 = await register("task-1")
    # Same instance — important for end-to-end (POST /steer must hit the same q)
    assert tq1 is tq2


@pytest.mark.asyncio
async def test_get_queues_after_register():
    await register("task-1")
    found = get_queues("task-1")
    assert found is not None
    assert found.steering.size == 0


@pytest.mark.asyncio
async def test_get_queues_unknown_returns_none():
    assert get_queues("nope") is None


@pytest.mark.asyncio
async def test_unregister_removes_entry():
    await register("task-1")
    assert "task-1" in active_task_ids()
    await unregister("task-1")
    assert "task-1" not in active_task_ids()
    assert get_queues("task-1") is None


@pytest.mark.asyncio
async def test_unregister_unknown_is_silent():
    # No exception expected
    await unregister("never-registered")


@pytest.mark.asyncio
async def test_concurrent_pushes_serialise_correctly():
    q = SteeringQueue()

    async def push_n(prefix: str, n: int):
        for i in range(n):
            await q.push(f"{prefix}{i}")

    await asyncio.gather(push_n("A", 10), push_n("B", 10), push_n("C", 10))
    drained = q.drain()
    assert len(drained) == 30
    contents = [m.content for m in drained]
    # Each prefix series stays internally ordered
    a_indices = [i for i, c in enumerate(contents) if c.startswith("A")]
    a_seq = [contents[i] for i in a_indices]
    assert a_seq == [f"A{i}" for i in range(10)]
