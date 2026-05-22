"""Tests for backend.agent_core.loop.run_loop — the main agent loop."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from backend.agent_core import steering as _steering
from backend.agent_core.events import AgentEvent, EventStream
from backend.agent_core.hooks import Hooks
from backend.agent_core.loop import run_loop
from backend.agent_core.messages import (
    AssistantMessage,
    SummaryMessage,
    ToolMessage,
    UserMessage,
)
from backend.agent_core.state import AgentState
from backend.agent_core.tool import ToolDefinition, ToolExecutor, ToolResult


@pytest.fixture(autouse=True)
def _clean_registry():
    _steering.clear_registry_for_tests()
    yield
    _steering.clear_registry_for_tests()


# ─── Helpers ─────────────────────────────────────────────────────────


@dataclass
class FakeResp:
    content: str = ""
    tool_calls: list[dict] = None
    thinking: str | None = None
    usage_metadata: dict | None = None
    response_metadata: dict | None = None
    additional_kwargs: dict | None = None

    def __post_init__(self):
        if self.tool_calls is None:
            self.tool_calls = []
        if self.usage_metadata is None:
            self.usage_metadata = {"input_tokens": 100, "output_tokens": 50}
        if self.response_metadata is None:
            self.response_metadata = {}


def _scripted_llm(*responses: FakeResp):
    """Returns an async llm_call that yields the provided responses sequentially."""
    it = iter(responses)

    async def call(messages, extras):
        try:
            return next(it)
        except StopIteration:
            return FakeResp(content="(no more scripted responses)")
    return call


def _make_state(task_id="task-test"):
    return AgentState(
        system_prompt="you are a test agent",
        model="gpt-4o",
        task_id=task_id,
    )


def _make_hooks():
    def convert_to_llm(messages):
        out = []
        for m in messages:
            if m.role in ("user", "assistant"):
                out.append({"role": m.role, "content": m.content})
            elif m.role == "tool":
                out.append({"role": "tool", "content": m.content, "tool_call_id": m.tool_call_id})
            elif m.role == "summary":
                out.append({"role": "user", "content": f"[summary] {m.content}"})
        return out
    return Hooks(convert_to_llm=convert_to_llm)


def _make_echo_tool():
    async def echo(args):
        return ToolResult(content=str(args))
    return ToolDefinition(
        name="echo",
        description="echo args back",
        schema={"type": "object"},
        execute=echo,
    )


async def _drain_events(stream: EventStream, task: asyncio.Task) -> list[AgentEvent]:
    """Subscribe and collect every event published during ``task``."""
    q = stream.subscribe()
    events: list[AgentEvent] = []

    async def collect():
        try:
            while True:
                ev = await asyncio.wait_for(q.get(), timeout=0.5)
                events.append(ev)
        except asyncio.TimeoutError:
            return

    collector = asyncio.create_task(collect())
    await task
    await asyncio.sleep(0.05)
    collector.cancel()
    try:
        await collector
    except asyncio.CancelledError:
        pass
    stream.unsubscribe(q)
    return events


# ─── Test cases ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_loop_terminates_when_no_tool_calls():
    state = _make_state()
    state.messages.append(UserMessage(content="hello"))
    stream = EventStream()
    llm = _scripted_llm(FakeResp(content="hi there"))
    tools = ToolExecutor({"echo": _make_echo_tool()})

    task = asyncio.create_task(
        run_loop(state, _make_hooks(), tools, llm, stream, max_turns=5)
    )
    events = await _drain_events(stream, task)
    types = [e.type for e in events]

    # Must contain at minimum agent_start, turn_start, message_start, message_end, turn_end, agent_end
    assert types.index("agent_start") < types.index("turn_start")
    assert "message_end" in types
    assert types[-1] == "agent_end"
    # Final state added one assistant message, no tool messages
    assert any(isinstance(m, AssistantMessage) for m in state.messages)


@pytest.mark.asyncio
async def test_loop_executes_tool_then_stops():
    state = _make_state()
    state.messages.append(UserMessage(content="please echo"))
    stream = EventStream()
    llm = _scripted_llm(
        FakeResp(content="", tool_calls=[
            {"id": "tc-1", "name": "echo", "args": {"x": 1}},
        ]),
        FakeResp(content="ok done"),
    )
    tools = ToolExecutor({"echo": _make_echo_tool()})

    task = asyncio.create_task(
        run_loop(state, _make_hooks(), tools, llm, stream, max_turns=5)
    )
    events = await _drain_events(stream, task)
    types = [e.type for e in events]

    assert "tool_execution_start" in types
    assert "tool_execution_end" in types
    assert types.count("turn_start") >= 2  # tool turn + final turn
    assert types[-1] == "agent_end"
    # State contains: original user, assistant(tool_call), tool_msg, final assistant
    assert any(isinstance(m, ToolMessage) for m in state.messages)


@pytest.mark.asyncio
async def test_loop_respects_max_turns():
    """If LLM keeps emitting tool_calls forever, loop must cap at max_turns."""
    state = _make_state()
    state.messages.append(UserMessage(content="loop forever"))
    stream = EventStream()

    async def call(messages, extras):
        # Always returns a tool_call; never the "done" plain message
        return FakeResp(content="", tool_calls=[
            {"id": f"tc-{len(messages)}", "name": "echo", "args": {}},
        ])

    tools = ToolExecutor({"echo": _make_echo_tool()})
    task = asyncio.create_task(
        run_loop(state, _make_hooks(), tools, _scripted_or(call), stream, max_turns=3)
    )
    events = await _drain_events(stream, task)
    end = next(e for e in events if e.type == "agent_end")
    assert end.data["final_status"] == "max_turns"
    assert end.data["total_turns"] == 3


def _scripted_or(call):
    """Identity helper to keep the scripted_llm typing pattern uniform."""
    return call


@pytest.mark.asyncio
async def test_loop_terminates_when_all_tools_request_terminate():
    state = _make_state()
    state.messages.append(UserMessage(content="early exit"))
    stream = EventStream()

    async def terminating_tool(args):
        return ToolResult(content="bye", terminate=True)

    tools = ToolExecutor({
        "term": ToolDefinition(
            name="term", description="", schema={"type": "object"},
            execute=terminating_tool,
        ),
    })

    llm = _scripted_llm(FakeResp(content="", tool_calls=[
        {"id": "tc-1", "name": "term", "args": {}},
    ]))

    task = asyncio.create_task(
        run_loop(state, _make_hooks(), tools, llm, stream, max_turns=5)
    )
    events = await _drain_events(stream, task)
    end = next(e for e in events if e.type == "agent_end")
    assert end.data["final_status"] == "completed"
    # Should not have called LLM a 2nd time after terminate
    assert sum(1 for e in events if e.type == "turn_start") == 1


@pytest.mark.asyncio
async def test_loop_drains_steering_before_each_turn():
    """A steering message pushed between turns must appear in transcript."""
    state = _make_state(task_id="task-steer")
    state.messages.append(UserMessage(content="initial"))
    stream = EventStream()

    pushed = {"done": False}

    async def call(messages, extras):
        # Capture the current message list snapshot for assertion
        if not pushed["done"]:
            # Inject steer before next turn
            queues = _steering.get_queues("task-steer")
            assert queues is not None, "loop should have registered the task"
            await queues.steering.push("STEER-1")
            pushed["done"] = True
            return FakeResp(content="", tool_calls=[
                {"id": "tc-1", "name": "echo", "args": {}},
            ])
        return FakeResp(content="final")

    tools = ToolExecutor({"echo": _make_echo_tool()})
    task = asyncio.create_task(
        run_loop(state, _make_hooks(), tools, call, stream, max_turns=5)
    )
    await task
    # The steer message should be in the transcript as a UserMessage
    contents = [m.content for m in state.messages if m.role == "user"]
    assert "STEER-1" in contents


@pytest.mark.asyncio
async def test_loop_followup_wakes_after_graceful_stop():
    """Agent finishes with no tool_calls; follow-up queue wakes it for one more turn."""
    state = _make_state(task_id="task-followup")
    state.messages.append(UserMessage(content="initial"))
    stream = EventStream()

    pushed = {"done": False}

    async def call(messages, extras):
        if not pushed["done"]:
            # Push a follow-up via the registry; the loop must wake & run another turn
            queues = _steering.get_queues("task-followup")
            assert queues is not None
            await queues.follow_up.push("FOLLOWUP-1")
            pushed["done"] = True
            return FakeResp(content="first ok")  # no tool_calls → would normally exit
        return FakeResp(content="second ok")

    tools = ToolExecutor({"echo": _make_echo_tool()})
    task = asyncio.create_task(
        run_loop(state, _make_hooks(), tools, call, stream, max_turns=5)
    )
    events = await _drain_events(stream, task)

    # Two assistant turns happened
    assistant_msgs = [m for m in state.messages if m.role == "assistant"]
    assert len(assistant_msgs) == 2
    end = next(e for e in events if e.type == "agent_end")
    assert end.data["final_status"] == "completed"


@pytest.mark.asyncio
async def test_loop_invokes_compaction_when_summarizer_provided():
    """Mock the summarizer callable; verify it's invoked when threshold crossed."""
    state = AgentState(system_prompt="", model="gpt-4")  # tiny window forces compaction
    state.task_id = "task-compact"
    # Build a transcript big enough to trigger
    big = "x" * 8000
    state.messages = []
    for i in range(20):
        state.messages.append(UserMessage(content=f"u{i} " + big))
        state.messages.append(AssistantMessage(content=f"a{i} " + big))

    stream = EventStream()

    summarizer_called = {"n": 0}

    async def summariser(prefix):
        summarizer_called["n"] += 1
        return "[recap]"

    async def call(messages, extras):
        return FakeResp(content="done")

    tools = ToolExecutor({"echo": _make_echo_tool()})
    task = asyncio.create_task(
        run_loop(
            state, _make_hooks(), tools, call, stream,
            max_turns=2, enable_compaction=True, summarizer=summariser,
        )
    )
    await task
    assert summarizer_called["n"] >= 1
    # Summary message is now first
    assert any(isinstance(m, SummaryMessage) for m in state.messages)


@pytest.mark.asyncio
async def test_loop_llm_exception_emits_error_and_aborts():
    state = _make_state(task_id="task-llm-err")
    state.messages.append(UserMessage(content="x"))
    stream = EventStream()

    async def call(messages, extras):
        raise RuntimeError("provider 500")

    tools = ToolExecutor({"echo": _make_echo_tool()})
    task = asyncio.create_task(
        run_loop(state, _make_hooks(), tools, call, stream, max_turns=5)
    )
    events = await _drain_events(stream, task)
    end = next(e for e in events if e.type == "agent_end")
    assert end.data["final_status"] == "failed"
    assert state.error_message and "500" in state.error_message


@pytest.mark.asyncio
async def test_loop_unregisters_task_on_completion():
    state = _make_state(task_id="task-cleanup")
    state.messages.append(UserMessage(content="x"))
    stream = EventStream()
    llm = _scripted_llm(FakeResp(content="done"))
    tools = ToolExecutor({"echo": _make_echo_tool()})

    await run_loop(state, _make_hooks(), tools, llm, stream, max_turns=3)
    # Registry should be clean after the task ends
    assert _steering.get_queues("task-cleanup") is None
