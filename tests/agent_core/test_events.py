"""Tests for backend.agent_core.events."""
from __future__ import annotations

import asyncio
import json

import pytest

from backend.agent_core.events import (
    EVENT_TYPES,
    AgentEvent,
    EventStream,
)


# ─── AgentEvent ──────────────────────────────────────────────────────


def test_event_types_count_is_nine():
    assert len(EVENT_TYPES) == 9
    assert "agent_start" in EVENT_TYPES
    assert "agent_end" in EVENT_TYPES


@pytest.mark.xfail(reason="Frontend listens on default 'message' channel; emitting event: line would break agent-console.js. Aspirational test — see backend/agent_core/events.py docstring.", strict=False)
def test_event_to_sse_format_has_three_lines_plus_terminator():
    e = AgentEvent(type="agent_start", task_id="t1", data={"model": "x"})
    sse = e.to_sse()
    # SSE block ends with a blank line (\n\n)
    assert sse.endswith("\n\n")
    head = sse.rstrip("\n")
    lines = head.split("\n")
    assert lines[0].startswith("event: agent_start")
    assert any(l.startswith("id: ") for l in lines)
    assert any(l.startswith("data: ") for l in lines)


def test_event_to_sse_data_is_valid_json():
    e = AgentEvent(type="turn_start", task_id="t1", data={"turn": 3})
    sse = e.to_sse()
    data_line = next(l for l in sse.split("\n") if l.startswith("data: "))
    payload = json.loads(data_line[len("data: "):])
    assert payload["type"] == "turn_start"
    assert payload["data"]["turn"] == 3
    assert payload["task_id"] == "t1"


def test_event_seq_monotonic():
    a = AgentEvent(type="agent_start", task_id="t1")
    b = AgentEvent(type="turn_start", task_id="t1")
    c = AgentEvent(type="agent_end", task_id="t2")
    assert b.seq > a.seq
    assert c.seq > b.seq


def test_event_timestamp_auto_populated():
    e = AgentEvent(type="agent_start", task_id="t1")
    assert e.timestamp > 0


def test_event_to_dict_round_trip():
    e = AgentEvent(type="message_update", task_id="t1", data={"delta": "hi"})
    d = e.to_dict()
    assert d["type"] == "message_update"
    assert d["data"] == {"delta": "hi"}
    # Modifying returned data shouldn't mutate the event
    d["data"]["delta"] = "X"
    assert e.data["delta"] == "hi"


# ─── EventStream ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_pub_sub_delivers_event():
    s = EventStream()
    q = s.subscribe()
    e = AgentEvent(type="agent_start", task_id="t1")
    await s.publish(e)
    received = await asyncio.wait_for(q.get(), timeout=1.0)
    assert received is e


@pytest.mark.asyncio
async def test_stream_multi_subscribers_each_get_event():
    s = EventStream()
    q1 = s.subscribe()
    q2 = s.subscribe()
    e = AgentEvent(type="turn_end", task_id="t1")
    await s.publish(e)
    r1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    r2 = await asyncio.wait_for(q2.get(), timeout=1.0)
    assert r1 is e and r2 is e
    assert s.subscriber_count == 2


@pytest.mark.asyncio
async def test_stream_unsubscribe_stops_delivery():
    s = EventStream()
    q = s.subscribe()
    s.unsubscribe(q)
    await s.publish(AgentEvent(type="agent_end", task_id="t1"))
    assert q.empty()
    assert s.subscriber_count == 0


@pytest.mark.asyncio
async def test_stream_full_queue_drops_event():
    s = EventStream(max_queue=2)
    q = s.subscribe()
    # Fill the queue
    await s.publish(AgentEvent(type="message_update", task_id="t1", data={"i": 1}))
    await s.publish(AgentEvent(type="message_update", task_id="t1", data={"i": 2}))
    # Third publish should drop (consumer hasn't drained)
    await s.publish(AgentEvent(type="message_update", task_id="t1", data={"i": 3}))
    assert s.dropped_count == 1
    # Still only 2 in queue
    assert q.qsize() == 2


@pytest.mark.asyncio
async def test_stream_unsubscribe_during_publish_safe():
    """Edge case: unsubscribing while publish iterates must not crash."""
    s = EventStream()
    q1 = s.subscribe()
    q2 = s.subscribe()

    # Drain q1 immediately so publish completes; then unsubscribe q2 mid-way
    # by aborting via no consumer.
    async def consumer():
        await q1.get()

    consume_task = asyncio.create_task(consumer())
    s.unsubscribe(q2)
    await s.publish(AgentEvent(type="agent_end", task_id="t1"))
    await asyncio.wait_for(consume_task, timeout=1.0)
