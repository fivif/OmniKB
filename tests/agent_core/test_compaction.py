"""Tests for backend.agent_core.compaction."""
from __future__ import annotations

import pytest

from backend.agent_core.compaction import (
    find_cut_point,
    maybe_compact,
    should_compact,
)
from backend.agent_core.messages import (
    AssistantMessage,
    SummaryMessage,
    ToolMessage,
    UserMessage,
)
from backend.agent_core.state import AgentState


# ─── Fixtures ─────────────────────────────────────────────────────────


def _msgs_long_dialog():
    """Build a dialog of ~120k tokens of repeated content (forces compaction)."""
    long_blob = "x" * 8000  # ~2700 tokens with cl100k_base for ASCII
    msgs = []
    # 20 alternating user/assistant turns; user msgs include 'STAMP-N'
    for i in range(20):
        msgs.append(UserMessage(content=f"STAMP-{i}\n" + long_blob))
        msgs.append(AssistantMessage(content=f"reply-{i}\n" + long_blob))
    return msgs


def _msgs_short():
    return [
        UserMessage(content="hi"),
        AssistantMessage(content="hello"),
    ]


# ─── should_compact ─────────────────────────────────────────────────


def test_should_compact_false_under_threshold():
    s = AgentState(system_prompt="", model="gpt-4o", messages=_msgs_short())
    assert should_compact(s) is False


def test_should_compact_true_when_over_threshold():
    # gpt-4o has 128k window; reserve=4096 -> trigger at >123904 tokens
    # Use a smaller-window model to make the test cheaper
    s = AgentState(system_prompt="", model="gpt-4", messages=_msgs_long_dialog())
    # gpt-4 has 8192 window -> our 120k+ dialog blows past it instantly
    assert should_compact(s) is True


# ─── find_cut_point ───────────────────────────────────────────────────


def test_find_cut_point_returns_zero_for_empty():
    assert find_cut_point([], 1000, "gpt-4o") == 0


def test_find_cut_point_returns_zero_when_too_short():
    msgs = _msgs_short()
    assert find_cut_point(msgs, 100000, "gpt-4o") == 0


def test_find_cut_point_lands_on_user_message():
    msgs = _msgs_long_dialog()
    cut = find_cut_point(msgs, keep_recent_tokens=8000, model="gpt-4")
    assert cut > 0
    assert msgs[cut].role == "user"


def test_find_cut_point_never_splits_tool_call_pair():
    """Construct a sequence: User → Assistant(tool_calls) → Tool result → User → ...

    A cut MUST land on a user message — never between an assistant tool_call
    and its tool_result (would orphan the tool result).
    """
    msgs = []
    for i in range(10):
        msgs.append(UserMessage(content="x" * 6000))
        msgs.append(AssistantMessage(
            content="",
            tool_calls=[{"tool_call_id": f"tc-{i}", "name": "search", "args": {}}],
        ))
        msgs.append(ToolMessage(tool_call_id=f"tc-{i}", tool_name="search", content="x" * 6000))
    cut = find_cut_point(msgs, keep_recent_tokens=8000, model="gpt-4")
    assert cut >= 0
    if cut > 0:
        # Cut must be on a user message
        assert msgs[cut].role == "user"


# ─── maybe_compact ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_maybe_compact_no_op_under_threshold():
    s = AgentState(system_prompt="", model="gpt-4o", messages=_msgs_short())
    called = []

    async def summariser(_):
        called.append(1)
        return "summary"

    did = await maybe_compact(s, summariser)
    assert did is False
    assert called == []
    assert all(not isinstance(m, SummaryMessage) for m in s.messages)


@pytest.mark.asyncio
async def test_maybe_compact_replaces_prefix_with_summary():
    msgs = _msgs_long_dialog()
    s = AgentState(system_prompt="", model="gpt-4", messages=list(msgs))
    original_count = len(s.messages)

    async def summariser(prefix):
        return f"[recap of {len(prefix)} msgs]"

    did = await maybe_compact(s, summariser, keep_recent_tokens=8000)
    assert did is True
    # First message must be SummaryMessage
    assert isinstance(s.messages[0], SummaryMessage)
    assert s.messages[0].content.startswith("[recap of")
    assert s.messages[0].summarized_count > 0
    # Total length is shorter
    assert len(s.messages) < original_count
    # Last messages still present
    last_user = s.messages[-2]  # last few maintained
    assert last_user.role in ("user", "assistant", "tool", "summary")


@pytest.mark.asyncio
async def test_maybe_compact_summariser_failure_aborts_safely():
    msgs = _msgs_long_dialog()
    s = AgentState(system_prompt="", model="gpt-4", messages=list(msgs))
    original = list(s.messages)

    async def summariser(_):
        raise RuntimeError("boom")

    did = await maybe_compact(s, summariser, keep_recent_tokens=8000)
    assert did is False
    assert s.messages == original  # untouched


@pytest.mark.asyncio
async def test_maybe_compact_empty_summary_aborts():
    msgs = _msgs_long_dialog()
    s = AgentState(system_prompt="", model="gpt-4", messages=list(msgs))

    async def summariser(_):
        return "   "  # whitespace only

    did = await maybe_compact(s, summariser, keep_recent_tokens=8000)
    assert did is False
    assert all(not isinstance(m, SummaryMessage) for m in s.messages)


@pytest.mark.asyncio
async def test_maybe_compact_records_summarized_token_count():
    msgs = _msgs_long_dialog()
    s = AgentState(system_prompt="", model="gpt-4", messages=list(msgs))

    async def summariser(_):
        return "ok"

    did = await maybe_compact(s, summariser, keep_recent_tokens=8000)
    assert did is True
    summary = s.messages[0]
    assert isinstance(summary, SummaryMessage)
    assert summary.summarized_tokens > 0
    assert summary.summarized_count > 0
