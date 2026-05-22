"""Tests for backend.agent_core.messages."""
from __future__ import annotations

import dataclasses
import json
from dataclasses import asdict

from backend.agent_core.messages import (
    AssistantMessage,
    SummaryMessage,
    ToolMessage,
    UserMessage,
)


def test_each_message_type_has_role_field():
    assert UserMessage().role == "user"
    assert AssistantMessage().role == "assistant"
    assert ToolMessage().role == "tool"
    assert SummaryMessage().role == "summary"


def test_summary_message_has_summarized_count():
    s = SummaryMessage(content="recap", summarized_count=12, summarized_tokens=4500)
    assert s.summarized_count == 12
    assert s.summarized_tokens == 4500
    assert s.role == "summary"


def test_assistant_message_supports_tool_calls():
    a = AssistantMessage(
        content="thinking…",
        tool_calls=[{"tool_call_id": "tc-1", "name": "search", "args": {"q": "x"}}],
    )
    assert a.tool_calls[0]["tool_call_id"] == "tc-1"
    assert a.tool_calls[0]["name"] == "search"


def test_tool_message_includes_full_log_path():
    t = ToolMessage(
        tool_call_id="tc-1",
        tool_name="bash",
        content="truncated preview…",
        full_log_path="/tmp/x.log",
    )
    field_names = {f.name for f in dataclasses.fields(t)}
    assert "full_log_path" in field_names
    assert t.full_log_path == "/tmp/x.log"


def test_messages_independent_default_collections():
    a = AssistantMessage()
    b = AssistantMessage()
    a.tool_calls.append({"x": 1})
    assert b.tool_calls == []


def test_message_round_trip_via_asdict():
    """All four message types serialise to JSON without losing fields."""
    msgs = [
        UserMessage(content="hi", timestamp=1.0),
        AssistantMessage(content="hello", thinking="…", timestamp=2.0),
        ToolMessage(tool_call_id="tc-1", tool_name="t", content="r", timestamp=3.0),
        SummaryMessage(content="recap", summarized_count=5, timestamp=4.0),
    ]
    payload = json.dumps([asdict(m) for m in msgs])
    parsed = json.loads(payload)
    assert parsed[0]["role"] == "user"
    assert parsed[1]["role"] == "assistant"
    assert parsed[2]["role"] == "tool"
    assert parsed[3]["role"] == "summary"
    assert parsed[3]["summarized_count"] == 5
