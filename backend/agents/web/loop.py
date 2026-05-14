"""web_agent_loop — agent_core.run_loop-driven agent loop for URL ingestion."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent_core.budget import BudgetTracker
from agent_core.compaction import make_llm_summarizer
from agent_core.events import EventStream
from agent_core.hooks import Hooks
from agent_core.messages import (
    AgentMessage,
    AssistantMessage,
    SummaryMessage,
    ToolMessage as CoreToolMessage,
    UserMessage,
)
from agent_core.state import AgentState
from agent_core.tool import ToolDefinition, ToolExecutor, ToolResult
from agent_core.loop import run_loop
from agents.doc_agent import RawDocument
from agents.web.handler import StepOutcome, WebHandler
from agents.web.research_state import ResearchState
from agents.web.session import WebSession

logger = logging.getLogger(__name__)


def _emit(msg, kind="progress", task_id=None):
    try:
        from utils.agent_bus import emit
        emit(msg, kind=kind, agent="orchestrator", task_id=task_id)
    except Exception:
        pass


# ─── LangChain bridge ───────────────────────────────────────────────

_PLAN_BLOCK_RE = re.compile(r"```plan\s*(\{[\s\S]*?\})\s*```", re.IGNORECASE)

_URL_TOOL_NAMES = {"http_get", "http_get_batch", "get_links", "browser_get_text"}


def _extract_urls_from_args(args: dict) -> list[str]:
    """Best-effort extract URL strings from tool args."""
    urls: list[str] = []
    for v in args.values():
        if isinstance(v, str) and v.startswith(("http://", "https://")):
            urls.append(v)
        elif isinstance(v, list):
            for s in v:
                if isinstance(s, str) and s.startswith(("http://", "https://")):
                    urls.append(s)
    return urls


def _build_convert_to_llm(research_state: ResearchState | None = None):
    """Return a convert_to_llm hook: AgentMessage[] → LangChain BaseMessage list.

    Also handles two side effects per call:
    1. Parse the ```plan {...}``` block from the first assistant message and
       lock the plan into research_state.
    2. Append a fresh research-state reminder at the end of the message list
       so the LLM sees structured progress every turn.
    """

    def convert_to_llm(messages: list[AgentMessage]) -> list:
        lc_msgs: list = []
        for m in messages:
            if isinstance(m, UserMessage):
                lc_msgs.append(HumanMessage(content=m.content))
            elif isinstance(m, AssistantMessage):
                ai = AIMessage(content=m.content)
                if m.tool_calls:
                    ai.tool_calls = [
                        {
                            "id": tc.get("tool_call_id", ""),
                            "name": tc["name"],
                            "args": tc["args"],
                        }
                        for tc in m.tool_calls
                    ]
                # DeepSeek requires reasoning_content round-trip:
                # assistant messages that had thinking must echo it back
                # in the next request. The langchain-openai monkey-patch
                # (agents/llm.py:_patched_serial) reads it from
                # additional_kwargs and writes it to the wire.
                if m.thinking:
                    ai.additional_kwargs = {"reasoning_content": m.thinking}
                lc_msgs.append(ai)
            elif isinstance(m, CoreToolMessage):
                lc_msgs.append(
                    ToolMessage(content=m.content, tool_call_id=m.tool_call_id)
                )
            elif isinstance(m, SummaryMessage):
                lc_msgs.append(
                    HumanMessage(content=f"## Earlier turns (compacted)\n{m.content}")
                )

        if research_state is not None:
            # Lazy plan parsing — once locked, skip
            if not research_state.plan_locked:
                for m in messages:
                    if isinstance(m, AssistantMessage) and m.content:
                        match = _PLAN_BLOCK_RE.search(m.content)
                        if match:
                            try:
                                plan = json.loads(match.group(1))
                                research_state.lock_plan(
                                    plan.get("subgoals", []) or [],
                                    plan.get("success_criteria", []) or [],
                                )
                            except Exception:
                                pass
                        break
            # Inject reminder as a final HumanMessage (a system reminder the
            # LLM sees just before its next response). Compose lightly so
            # we don't blow context.
            rem = research_state.to_reminder()
            if rem:
                lc_msgs.append(HumanMessage(content=rem))

        return lc_msgs

    return convert_to_llm


def _build_executor(handler: WebHandler, research_state: ResearchState | None = None) -> ToolExecutor:
    """Wrap handler._tools (LangChain @tool fns) as agent_core ToolDefinitions.

    Each tool execution updates research_state.attempted_tools and, for URL-fetching
    tools, marks visited URLs.
    """

    tool_defs: dict[str, ToolDefinition] = {}
    for t in handler._tools:
        schema: dict[str, Any] = {"type": "object", "properties": {}}
        if hasattr(t, "args_schema") and t.args_schema is not None:
            try:
                schema = t.args_schema.model_json_schema()
            except Exception:
                pass

        async def _execute(args: dict, _tool: Any = t) -> ToolResult:
            if research_state is not None:
                research_state.record_tool(_tool.name)
                if _tool.name in _URL_TOOL_NAMES:
                    for u in _extract_urls_from_args(args):
                        research_state.mark_visited(u)
            try:
                if hasattr(_tool, "ainvoke"):
                    result = await _tool.ainvoke(args)
                else:
                    result = _tool.invoke(args)
                return ToolResult(content=str(result))
            except Exception as exc:
                logger.warning("tool %s error: %s", _tool.name, exc)
                return ToolResult(
                    content=f"[{_tool.name} error: {exc}]", error=str(exc)
                )

        tool_defs[t.name] = ToolDefinition(
            name=t.name,
            description=t.description or "",
            schema=schema,
            execute=_execute,
        )

    return ToolExecutor(tool_defs)


def _resolve_model_name(handler: WebHandler) -> str:
    llm = handler._llm
    for attr in ("model_name", "model", "name"):
        val = getattr(llm, attr, None)
        if val:
            return val
    return "default"


def _derive_outcome(state: AgentState) -> StepOutcome:
    """Derive a StepOutcome from the final agent state.

    Priority:
    1. Last assistant narrative — the synthesised answer.
    2. Concatenated tool results — safety net so we don't lose fetched
       content when the LLM exited mid-execution (max_turns reached,
       budget exceeded, or final turn contained only tool calls).
    3. Error message if everything else is empty.
    """
    last_content = ""
    for m in reversed(state.messages):
        if isinstance(m, AssistantMessage) and m.content:
            last_content = str(m.content).strip()
            if last_content:
                break

    if last_content:
        return StepOutcome(data=last_content, should_exit=True)

    # Fallback: stitch together what the tools actually fetched.
    tool_bodies: list[str] = []
    for m in state.messages:
        if not isinstance(m, CoreToolMessage):
            continue
        body = str(m.content or "").strip()
        if not body or body.startswith("["):
            # Skip empty placeholders and pure error markers like
            # "[http_get error: ...]" which add no real content.
            continue
        tag = getattr(m, "tool_name", "") or ""
        prefix = f"## {tag}\n" if tag else ""
        tool_bodies.append(prefix + body)

    fallback = "\n\n---\n\n".join(tool_bodies).strip()
    if fallback:
        logger.info(
            "web agent finished without final narrative; "
            "salvaged %d tool result(s) totalling %d chars",
            len(tool_bodies), len(fallback),
        )
        return StepOutcome(data=fallback, should_exit=True)

    if state.error_message:
        return StepOutcome(data=state.error_message, should_exit=False)
    return StepOutcome(data="", should_exit=False)


# ─── Main loop ──────────────────────────────────────────────────────


async def web_agent_loop(
    *,
    session: WebSession,
    handler: WebHandler,
    url: str,
    intent: str,
    event_stream: EventStream | None = None,
    budget: "BudgetTracker | None" = None,
) -> StepOutcome:
    """Run the web agent loop using agent_core.run_loop.

    Pre-loop: skill recall, build system prompt.
    Loop:     agent_core.run_loop (steering, compaction, tool exec, typed events).
    Post-loop: persist session, crystallize skills.
    """

    # ── Pre-loop: skill recall ──────────────────────────────────────
    skill_hint = await handler.recall_skill_passive()
    if skill_hint:
        _emit(
            f"recall hit: {skill_hint.count('## Skill:')} skills",
            task_id=handler.task_id,
        )

    # ── Pre-loop: URL strategy analysis (best-effort) ───────────────
    analyst_hint = ""
    try:
        from agents.url_analyst import analyze_url  # type: ignore
        res = await analyze_url(url)  # type: ignore[misc]
        if isinstance(res, dict):
            analyst_hint = (res.get("hint") or res.get("summary") or json.dumps(res, ensure_ascii=False))[:500]
        elif res:
            analyst_hint = str(res)[:500]
    except Exception as exc:
        logger.debug("url_analyst skipped: %s", exc)

    sys_prompt = handler.build_system_prompt(skill_hint=skill_hint, analyst_hint=analyst_hint)

    await session.append("system", sys_prompt)
    user_content = (
        f"URL: {url}\nUser intent: {intent or 'general - extract useful information'}"
    )
    await session.append("user", user_content)

    # ── Build agent_core dependencies ───────────────────────────────
    # Use the research_state already attached to the handler so that
    # record_fact / close_subgoal / self_check tools share the same instance.
    research_state = handler.research_state
    if research_state is None:
        research_state = ResearchState()
        handler.research_state = research_state
    research_state.mark_visited(url)  # the entry URL is implicitly "known"

    state = AgentState(
        system_prompt=sys_prompt,
        model=_resolve_model_name(handler),
        task_id=handler.task_id,
        session_id=session.id,
    )
    state.messages.append(UserMessage(content=user_content))

    hooks = Hooks(convert_to_llm=_build_convert_to_llm(research_state))
    executor = _build_executor(handler, research_state)

    async def _llm_call(messages: list, extras: dict) -> Any:
        sys_prompt_text = extras.get("system_prompt", "")
        full = [SystemMessage(content=sys_prompt_text)] + list(messages)
        from agents.llm import preserve_reasoning
        return await handler._llm_bound.ainvoke(preserve_reasoning(full))

    summarizer = make_llm_summarizer(handler._llm)

    # Resolve event stream
    if event_stream is None:
        from agent_core.events import get_event_stream
        event_stream = get_event_stream()

    # ── Run ─────────────────────────────────────────────────────────
    reflection_interval = 0
    try:
        from config import settings as _cfg
        reflection_interval = getattr(_cfg, "web_agent_reflection_interval", 8) or 0
    except Exception:
        pass

    state = await run_loop(
        state=state,
        hooks=hooks,
        tools=executor,
        llm_call=_llm_call,
        event_stream=event_stream,
        max_turns=handler.max_turns,
        summarizer=summarizer,
        budget=budget,
        reflection_interval=reflection_interval,
    )
    # Expose terminal status on the handler so run_agent can attach it to
    # the returned RawDocument metadata.
    handler._last_final_status = state.final_status  # type: ignore[attr-defined]

    # ── Post-loop: persist session messages ─────────────────────────
    for msg in state.messages[1:]:  # skip initial user message (already persisted)
        if isinstance(msg, UserMessage):
            await session.append("user", msg.content)
        elif isinstance(msg, AssistantMessage):
            await session.append(
                "assistant",
                msg.content,
                tool_calls=msg.tool_calls if msg.tool_calls else None,
            )
        elif isinstance(msg, CoreToolMessage):
            await session.append("tool", msg.content)

    # ── Post-loop: crystallization ──────────────────────────────────
    final_outcome = _derive_outcome(state)
    if final_outcome.data and final_outcome.should_exit:
        try:
            convert = _build_convert_to_llm()
            lc_msgs = convert(state.messages)
            sid = await handler.maybe_crystallize(lc_msgs, final_outcome.data)
            if sid:
                _emit(f"saved skill {sid[:8]}", kind="success", task_id=handler.task_id)
        except Exception as exc:
            logger.debug("crystallize failed: %s", exc)

    await session.set_status(
        "done" if final_outcome.should_exit else "max_turns"
    )
    return final_outcome


def _default_budget() -> BudgetTracker:
    """Sensible defaults so a runaway agent doesn't burn the wallet.

    Values tunable via settings (web_agent_*) — see config.Settings.
    """
    try:
        from config import settings as _cfg  # type: ignore
        return BudgetTracker(
            max_input_tokens=getattr(_cfg, "web_agent_max_input_tokens", 200_000) or None,
            max_output_tokens=getattr(_cfg, "web_agent_max_output_tokens", 50_000) or None,
            max_seconds=getattr(_cfg, "web_agent_max_seconds", 300.0) or None,
            max_total_tool_calls=getattr(_cfg, "web_agent_max_tool_calls", 0) or None,
        )
    except Exception:
        return BudgetTracker(
            max_input_tokens=200_000,
            max_output_tokens=50_000,
            max_seconds=300.0,
        )


async def run_agent(
    url: str,
    intent: str = "",
    task_id: str = None,
    *,
    budget: BudgetTracker | None = None,
) -> RawDocument:
    """High-level entry. Creates a session, runs the loop, returns RawDocument."""
    extra_tools = []
    try:
        import sys
        main_mod = sys.modules.get("__main__") or sys.modules.get("main")
        if main_mod:
            extra_tools = list(getattr(main_mod.app.state, "jshook_tools", []) or [])
    except Exception:
        pass

    session = await WebSession.create(task_id=task_id)
    research_state = ResearchState()
    handler = WebHandler(
        url=url,
        intent=intent,
        task_id=task_id,
        extra_tools=extra_tools,
        research_state=research_state,
    )

    # Resolve event stream for this run
    from agent_core.events import get_event_stream
    event_stream = get_event_stream()
    log_es = logging.getLogger(__name__)
    log_es.info(
        "run_agent: event_stream=%s subscribers=%d",
        type(event_stream).__name__ if event_stream else None,
        event_stream.subscriber_count if event_stream else 0,
    )

    outcome = await web_agent_loop(
        session=session,
        handler=handler,
        url=url,
        intent=intent,
        event_stream=event_stream,
        budget=budget if budget is not None else _default_budget(),
    )

    content_str = str(outcome.data) if outcome.data is not None else ""
    return RawDocument(
        content=content_str,
        metadata={
            "file_type": "url",
            "source_url": url,
            "fetch_mode": "smart_v2",
            "session_id": session.id,
            "facts_collected": len(research_state.facts),
            "self_check_passed": research_state.self_check_passed,
            "agent_final_status": getattr(handler, "_last_final_status", None),
        },
    )
