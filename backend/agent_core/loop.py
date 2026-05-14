"""run_loop — the agent loop's beating heart.

5-step Turn Lifecycle (mirrors pi-agent-core's runLoop):

    ┌──────────────────────────────────────────────────────────────┐
    │ for turn in range(max_turns):                                 │
    │   1. ContextTransform   — drain steering, run compaction,     │
    │                           apply transform_context hook,       │
    │                           apply convert_to_llm + cache prep   │
    │   2. LLMStream          — call provider, parse content +      │
    │                           tool_calls + thinking + usage       │
    │   3. ToolExec           — ToolExecutor.execute_batch          │
    │   4. SteeringCheck      — drain incoming steers; restart turn │
    │                           when present; otherwise consider    │
    │                           follow-up wakes                     │
    │   5. GracefulStop       — emit agent_end + return state       │
    └──────────────────────────────────────────────────────────────┘

The loop is provider-agnostic: callers inject ``llm_call`` (a callable that
returns whatever the LLM SDK returns) and ``hooks.convert_to_llm`` (a
callable that translates AgentMessage ↔ provider format).

All side effects (events, tool exec, file writes) flow through dependency-
injected collaborators, which makes ``run_loop`` cleanly unit-testable with
synthetic LLMs and tools.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any, Awaitable, Callable

from . import steering
from .budget import BudgetTracker
from .cache import adapter as _cache_adapter, detect_provider, log_cache_stats
from .compaction import Summarizer, maybe_compact
from .events import AgentEvent, EventStream
from .hooks import Hooks
from .messages import AssistantMessage, ToolMessage, UserMessage
from .state import AgentState
from .tokens import count_messages_tokens
from .tool import ToolExecutor, ToolResult
from .truncate import OutputAccumulator

logger = logging.getLogger(__name__)


LlmCallable = Callable[[list[dict[str, Any]], dict[str, Any]], Awaitable[Any]]
"""``async def(messages, extras) -> response``.

``response`` must expose ``.content`` (str), optional ``.tool_calls`` (list
of ``{tool_call_id, name, args}`` dicts), optional ``.thinking`` (str),
and optional ``.usage_metadata`` / ``.response_metadata`` for cache stats.

``extras`` carries the prepared system prompt (Anthropic block list or str)
and any other provider-specific metadata. Callers that don't care about
extras may simply ignore it.
"""


def _sha_short(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


def _args_preview(call: dict[str, Any], max_chars: int = 120) -> str:
    name = call.get("name") or call.get("tool_name") or "?"
    args = call.get("args") or {}
    rendered = json.dumps(args, ensure_ascii=False, default=str)
    if len(rendered) > max_chars:
        rendered = rendered[: max_chars - 3] + "..."
    return f"{name}({rendered})"


def _normalize_call(tc: dict[str, Any]) -> dict[str, Any]:
    """Normalise a langchain tool_call dict to ToolExecutor's expected shape."""
    tc_id = tc.get("tool_call_id") or tc.get("id") or ""
    return {
        "tool_call_id": tc_id,
        "name": tc.get("name") or tc.get("tool_name") or "",
        "args": tc.get("args") or tc.get("arguments") or {},
    }


def _extract_response_fields(response: Any) -> tuple[str, list[dict], str | None, dict[str, Any] | None]:
    """Tease apart content / tool_calls / thinking / usage from a langchain-ish response."""
    content = getattr(response, "content", None)
    if isinstance(content, list):
        # Anthropic-style content blocks: extract text only
        content = "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    content = str(content or "")

    tool_calls = list(getattr(response, "tool_calls", None) or [])
    # Normalise each call to a dict (langchain returns dicts already; some SDKs use objects)
    norm_calls: list[dict] = []
    for tc in tool_calls:
        if isinstance(tc, dict):
            norm_calls.append({
                "tool_call_id": tc.get("id") or tc.get("tool_call_id") or "",
                "name": tc.get("name", ""),
                "args": tc.get("args", tc.get("arguments", {})),
            })
        else:
            norm_calls.append({
                "tool_call_id": getattr(tc, "id", "") or getattr(tc, "tool_call_id", ""),
                "name": getattr(tc, "name", ""),
                "args": getattr(tc, "args", {}) or getattr(tc, "arguments", {}),
            })

    thinking = getattr(response, "thinking", None)
    if not thinking:
        # langchain reasoning models put it under additional_kwargs.reasoning_content
        kw = getattr(response, "additional_kwargs", {}) or {}
        thinking = kw.get("reasoning_content")

    usage = getattr(response, "usage_metadata", None)
    if not usage:
        meta = getattr(response, "response_metadata", {}) or {}
        usage = meta.get("token_usage") or meta.get("usage")
    if usage and not isinstance(usage, dict):
        usage = None

    return content, norm_calls, thinking, usage


# ─── Main loop ───────────────────────────────────────────────────────


async def run_loop(
    state: AgentState,
    hooks: Hooks,
    tools: ToolExecutor,
    llm_call: LlmCallable,
    event_stream: EventStream,
    *,
    max_turns: int = 20,
    enable_compaction: bool = True,
    enable_cache: bool = True,
    summarizer: Summarizer | None = None,
    budget: BudgetTracker | None = None,
    reflection_interval: int = 0,
) -> AgentState:
    """Drive the agent until a terminal condition is reached.

    Mutates ``state`` in place AND returns it for convenience.

    If ``budget`` is supplied, it gates the loop at two points:
    * Before each LLM call (``check_pre_llm``) — terminate the run cleanly.
    * Before each tool dispatch (``check_pre_tool``) — substitute a synthetic
      error ToolResult so the LLM sees that a specific tool is exhausted but
      the run continues.
    """
    if not state.task_id:
        # task_id is required for steering registry & event correlation
        state.task_id = f"task-{int(time.time() * 1000)}"

    if budget is not None:
        budget.start()

    queues = await steering.register(state.task_id)

    await event_stream.publish(AgentEvent(
        type="agent_start",
        task_id=state.task_id,
        data={
            "session_id": state.session_id,
            "model": state.model,
            "system_prompt_hash": "sha256:" + _sha_short(state.system_prompt),
            "system_prompt_tokens": count_messages_tokens(
                [UserMessage(content=state.system_prompt)], state.model
            ),
        },
    ))

    final_status = "max_turns"
    cumulative_input = 0
    cumulative_output = 0
    cumulative_cached = 0
    budget_reason: str | None = None
    total_tool_calls_this_run = 0  # for reflection checkpoints

    # Compose budget-aware before_hook on top of caller's hook (if any)
    user_before_hook = hooks.before_tool_call

    async def _budget_before_hook(tool_name: str, args: dict[str, Any]):
        if budget is not None:
            reason = budget.check_pre_tool(tool_name)
            if reason:
                return {"block": True, "reason": reason}
            # Account this attempt BEFORE the call so subsequent caps see it
            budget.tick_tool_call(tool_name)
        if user_before_hook is not None:
            return await user_before_hook(tool_name, args)
        return None

    try:
        for turn in range(max_turns):
            state.turn = turn

            # ───── Step 1: Context Transform ─────
            for s in queues.steering.drain():
                state.messages.append(UserMessage(content=s.content))

            # ───── Budget pre-LLM check ─────
            if budget is not None:
                budget_reason = budget.check_pre_llm()
                if budget_reason:
                    final_status = "budget_exceeded"
                    state.error_message = budget_reason
                    logger.info("budget exceeded before turn %d: %s", turn, budget_reason)
                    break

            compacted = False
            if enable_compaction and summarizer is not None:
                try:
                    compacted = await maybe_compact(state, summarizer)
                except Exception as exc:
                    logger.warning("compaction failed (non-fatal): %s", exc)

            ctx_messages = state.messages
            if hooks.transform_context:
                try:
                    ctx_messages = hooks.transform_context(state.messages)
                except Exception as exc:
                    logger.warning("transform_context failed (non-fatal): %s", exc)

            llm_messages = hooks.convert_to_llm(ctx_messages)

            extras: dict[str, Any] = {"system_prompt": state.system_prompt}
            if enable_cache:
                provider = detect_provider(state.model)
                system_prepared, llm_messages = _cache_adapter.prepare_messages(
                    provider, state.system_prompt, llm_messages,
                )
                extras["system_prompt"] = system_prepared
                extras["provider"] = provider

            input_token_estimate = count_messages_tokens(ctx_messages, state.model)
            await event_stream.publish(AgentEvent(
                type="turn_start",
                task_id=state.task_id,
                data={"turn": turn, "input_tokens_estimated": input_token_estimate},
            ))

            # ───── Step 2: LLM Stream ─────
            msg_id = f"msg-{state.task_id}-{turn}"
            state.is_streaming = True
            await event_stream.publish(AgentEvent(
                type="message_start",
                task_id=state.task_id,
                data={"message_id": msg_id, "role": "assistant"},
            ))

            try:
                response = await llm_call(llm_messages, extras)
            except asyncio.CancelledError:
                state.is_streaming = False
                state.error_message = "llm_call cancelled (interrupt)"
                final_status = "aborted"
                await event_stream.publish(AgentEvent(
                    type="message_end",
                    task_id=state.task_id,
                    data={"message_id": msg_id, "error": {"code": "cancelled", "message": "interrupted"}},
                ))
                break
            except Exception as exc:
                state.is_streaming = False
                state.error_message = str(exc)
                final_status = "failed"
                logger.exception("llm_call failed: %s", exc)
                await event_stream.publish(AgentEvent(
                    type="message_end",
                    task_id=state.task_id,
                    data={"message_id": msg_id, "error": {"code": "llm_error", "message": str(exc)}},
                ))
                break

            state.is_streaming = False
            content, tool_calls, thinking, usage = _extract_response_fields(response)

            # Cache accounting
            if enable_cache and usage:
                try:
                    cstats = _cache_adapter.extract_stats(
                        detect_provider(state.model), state.model, usage,
                    )
                    cumulative_input += cstats.input_tokens
                    cumulative_output += cstats.output_tokens
                    cumulative_cached += cstats.cached_tokens
                    await log_cache_stats(cstats)
                    if budget is not None:
                        budget.tick_usage(
                            input_tokens=cstats.input_tokens,
                            output_tokens=cstats.output_tokens,
                            cached_tokens=cstats.cached_tokens,
                        )
                except Exception as exc:
                    logger.debug("cache stats log failed: %s", exc)

            await event_stream.publish(AgentEvent(
                type="message_end",
                task_id=state.task_id,
                data={
                    "message_id": msg_id,
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls,
                    "tokens": {
                        "input": (usage or {}).get("input_tokens") or (usage or {}).get("prompt_tokens", 0) or 0,
                        "output": (usage or {}).get("output_tokens") or (usage or {}).get("completion_tokens", 0) or 0,
                    } if usage else None,
                },
            ))

            state.messages.append(AssistantMessage(
                content=content,
                tool_calls=tool_calls,
                thinking=thinking,
            ))

            # ───── Step 3: Tool Execution ─────
            if not tool_calls:
                await event_stream.publish(AgentEvent(
                    type="turn_end",
                    task_id=state.task_id,
                    data={
                        "turn": turn,
                        "duration_ms": 0,
                        "compaction_triggered": compacted,
                    },
                ))

                # ───── Step 4: SteeringCheck ─────
                if queues.steering.peek():
                    continue

                # ───── Step 5: GracefulStop or Follow-up wake ─────
                follow_ups = queues.follow_up.drain()
                if follow_ups:
                    for f in follow_ups:
                        state.messages.append(UserMessage(content=f.content))
                    continue

                final_status = "completed"
                break

            # Tool calls present — execute the batch
            tool_t0 = time.monotonic()
            for tc in tool_calls:
                await event_stream.publish(AgentEvent(
                    type="tool_execution_start",
                    task_id=state.task_id,
                    data={
                        "tool_call_id": tc["tool_call_id"],
                        "tool_name": tc["name"],
                        "args": tc["args"],
                        "args_preview": _args_preview(tc),
                    },
                ))
                state.pending_tool_calls.add(tc["tool_call_id"])

            results = await tools.execute_batch(
                [_normalize_call(tc) for tc in tool_calls],
                before_hook=_budget_before_hook,
                after_hook=hooks.after_tool_call,
            )

            # Process each result: accumulate, truncate, append ToolMessage
            for (tc, (rid, result)) in zip(tool_calls, results):
                state.pending_tool_calls.discard(rid)
                acc = OutputAccumulator(state.task_id or "no-task", rid)
                await acc.feed(str(result.content))
                preview, log_path = await acc.finalize()

                state.messages.append(ToolMessage(
                    tool_call_id=rid,
                    tool_name=tc["name"],
                    content=preview,
                    full_log_path=log_path,
                ))

                await event_stream.publish(AgentEvent(
                    type="tool_execution_end",
                    task_id=state.task_id,
                    data={
                        "tool_call_id": rid,
                        "tool_name": tc["name"],
                        "status": "error" if result.error else "success",
                        "result_preview": preview[:2000],
                        "result_truncated": log_path is not None,
                        "result_log_path": log_path,
                        "duration_ms": int((time.monotonic() - tool_t0) * 1000),
                        "error": (
                            {"code": "tool_error", "message": result.error}
                            if result.error else None
                        ),
                        "terminate_hint": bool(result.terminate),
                    },
                ))

            # ── Reflection checkpoint ─────────────────────────────────
            total_tool_calls_this_run += len(tool_calls)
            if reflection_interval > 0 and total_tool_calls_this_run > 0:
                checkpoint = (total_tool_calls_this_run // reflection_interval) * reflection_interval
                prev_checkpoint = ((total_tool_calls_this_run - len(tool_calls)) // reflection_interval) * reflection_interval
                if checkpoint > prev_checkpoint:
                    state.messages.append(UserMessage(content=(
                        f"## Reflection checkpoint ({total_tool_calls_this_run} tool calls so far)\n\n"
                        "Pause and review your progress:\n"
                        "- What data have you collected? Summarize key findings.\n"
                        "- Which subgoals are satisfied? Call close_subgoal for any completed ones.\n"
                        "- What remains? Is your current approach working?\n"
                        "- Adjust your plan if needed, then continue."
                    )))
                    logger.info(
                        "reflection checkpoint at %d tool calls (task=%s)",
                        total_tool_calls_this_run, state.task_id,
                    )

            await event_stream.publish(AgentEvent(
                type="turn_end",
                task_id=state.task_id,
                data={
                    "turn": turn,
                    "duration_ms": int((time.monotonic() - tool_t0) * 1000),
                    "compaction_triggered": compacted,
                },
            ))

            # If every tool requested termination, stop now (skip auto follow-up LLM call)
            if results and all(r.terminate for _, r in results):
                final_status = "completed"
                break

        else:
            # for-else: the loop ran to max_turns without break
            final_status = "max_turns"

        cumulative_denominator = cumulative_input + sum(
            0 for _ in []  # placeholder; cache_creation summed elsewhere if needed
        )
        cache_hit_rate = (
            cumulative_cached / cumulative_input if cumulative_input > 0 else 0.0
        )

        end_data: dict[str, Any] = {
            "session_id": state.session_id,
            "final_status": final_status,
            "total_turns": state.turn + 1,
            "total_tokens": {
                "input": cumulative_input,
                "output": cumulative_output,
                "cached": cumulative_cached,
            },
            "cache_hit_rate": round(cache_hit_rate, 4),
            "error": state.error_message,
        }
        if budget is not None:
            end_data["budget"] = budget.snapshot()
            if budget_reason:
                end_data["budget_reason"] = budget_reason

        state.final_status = final_status

        await event_stream.publish(AgentEvent(
            type="agent_end",
            task_id=state.task_id,
            data=end_data,
        ))

        return state

    finally:
        await steering.unregister(state.task_id)
