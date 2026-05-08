"""web_agent_loop - generator-driven agent loop for URL ingestion."""
from __future__ import annotations

import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agents.doc_agent import RawDocument
from agents.web.handler import StepOutcome, WebHandler
from agents.web.session import WebSession

logger = logging.getLogger(__name__)


def _emit(msg, kind="progress", task_id=None):
    try:
        from utils.agent_bus import emit
        emit(msg, kind=kind, agent="orchestrator", task_id=task_id)
    except Exception:
        pass


async def web_agent_loop(*, session: WebSession, handler: WebHandler, url: str, intent: str) -> StepOutcome:
    skill_hint = await handler.recall_skill_passive()
    if skill_hint:
        _emit(f"recall hit: {skill_hint.count('## Skill:')} skills", task_id=handler.task_id)

    sys_prompt = handler.build_system_prompt(skill_hint)
    sys_msg = SystemMessage(content=sys_prompt)
    human = HumanMessage(content=f"URL: {url}\nUser intent: {intent or 'general - extract useful information'}")

    await session.append("system", sys_prompt)
    await session.append("user", human.content)

    messages = [sys_msg, human]
    final_outcome = StepOutcome(data="")

    for turn in range(handler.max_turns):
        if turn > 0 and turn % 5 == 0:
            messages = await handler.compact(messages)

        _emit(f"turn {turn + 1}", task_id=handler.task_id)
        try:
            response = await handler.llm_call(messages)
        except Exception as exc:
            logger.error("LLM call failed: %s", exc)
            final_outcome = StepOutcome(data=f"[LLM error: {exc}]", should_exit=True)
            break

        messages.append(response)
        await session.append(
            "assistant",
            str(response.content) if response.content else "",
            tool_calls=getattr(response, "tool_calls", None),
        )

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            final_outcome = StepOutcome(data=response.content, should_exit=True)
            break

        exit_inner = False
        for tc in tool_calls:
            tool_name = tc["name"]
            tool_args = tc.get("args", {})
            tool_call_id = tc["id"]
            _emit(f"call {tool_name}", task_id=handler.task_id)
            outcome = await handler.dispatch(tool_name, tool_args)
            content = str(outcome.data)[:8000]
            tm = ToolMessage(content=content, tool_call_id=tool_call_id)
            messages.append(tm)
            await session.append("tool", content)
            if outcome.should_exit:
                final_outcome = outcome
                exit_inner = True
                break
        if exit_inner:
            break

    if final_outcome.data and final_outcome.should_exit:
        try:
            sid = await handler.maybe_crystallize(messages, final_outcome.data)
            if sid:
                _emit(f"saved skill {sid[:8]}", kind="success", task_id=handler.task_id)
        except Exception as exc:
            logger.debug("crystallize failed: %s", exc)

    await session.set_status("done" if final_outcome.should_exit else "max_turns")
    return final_outcome


async def run_agent(url: str, intent: str = "", task_id: str = None) -> RawDocument:
    """High-level entry. Creates a session, runs the loop, returns RawDocument."""
    extra_tools = []
    try:
        from main import app
        extra_tools = list(getattr(app.state, "jshook_tools", []) or [])
    except Exception:
        pass

    session = await WebSession.create(task_id=task_id)
    handler = WebHandler(url=url, intent=intent, task_id=task_id, extra_tools=extra_tools)
    outcome = await web_agent_loop(session=session, handler=handler, url=url, intent=intent)

    content_str = str(outcome.data) if outcome.data is not None else ""
    return RawDocument(
        content=content_str,
        metadata={
            "file_type": "url",
            "source_url": url,
            "fetch_mode": "smart_v2",
            "session_id": session.id,
        },
    )
