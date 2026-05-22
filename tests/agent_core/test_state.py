"""Tests for backend.agent_core.state.AgentState."""
from __future__ import annotations

import json
from dataclasses import asdict

from backend.agent_core.state import AgentState


def test_state_default_init():
    s = AgentState(system_prompt="hi", model="m")
    assert s.system_prompt == "hi"
    assert s.model == "m"
    assert s.messages == []
    assert s.is_streaming is False
    assert s.pending_tool_calls == set()
    assert s.error_message is None
    assert s.turn == 0
    assert s.task_id is None
    assert s.session_id is None


def test_state_pending_tool_calls_is_set():
    s = AgentState(system_prompt="", model="")
    s.pending_tool_calls.add("tc-1")
    s.pending_tool_calls.add("tc-2")
    s.pending_tool_calls.add("tc-1")  # dup
    assert s.pending_tool_calls == {"tc-1", "tc-2"}
    assert isinstance(s.pending_tool_calls, set)


def test_state_serializable_to_dict():
    s = AgentState(
        system_prompt="hi",
        model="m",
        task_id="task-1",
        session_id="sess-1",
        turn=3,
    )
    s.pending_tool_calls.add("tc-x")
    d = asdict(s)
    # asdict turns sets into the same set type; coerce to list for JSON
    d["pending_tool_calls"] = sorted(d["pending_tool_calls"])
    payload = json.dumps(d)
    parsed = json.loads(payload)
    assert parsed["system_prompt"] == "hi"
    assert parsed["model"] == "m"
    assert parsed["task_id"] == "task-1"
    assert parsed["turn"] == 3
    assert parsed["pending_tool_calls"] == ["tc-x"]


def test_state_independent_default_collections():
    """Each instance gets its own list/set (not shared)."""
    a = AgentState(system_prompt="", model="")
    b = AgentState(system_prompt="", model="")
    a.pending_tool_calls.add("x")
    assert "x" not in b.pending_tool_calls
    assert a.messages is not b.messages
