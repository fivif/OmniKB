"""Token-based auto compaction.

Replaces the older ``turn % 5`` heuristic in ``agents/web/handler.py`` with
a token-aware strategy modelled after pi-agent-core (see earendil-works/pi
``packages/coding-agent/src/core/compaction/compaction.ts``):

1. Trigger only when ``count_messages_tokens(state.messages, model)``
   exceeds ``context_window(model) - reserve_tokens``.
2. Walk backwards from the latest message to find a USER message ``cut``
   such that ``messages[cut:]`` already contains ``keep_recent_tokens``.
   Cutting on a user message guarantees we never split a tool_call /
   tool_result pair (which would crash some providers).
3. LLM summarises ``messages[:cut]`` into a short ``SummaryMessage``.
4. ``state.messages`` is replaced in-place with ``[SummaryMessage, *kept]``.

Expose ``maybe_compact()`` (called by run_loop before every turn) and
``find_cut_point()`` (kept public for unit tests + audits).
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

from .messages import AgentMessage, SummaryMessage
from .state import AgentState
from .tokens import context_window, count_messages_tokens, count_tokens

logger = logging.getLogger(__name__)


SUMMARY_SYSTEM_PROMPT = (
    "Summarise the following agent turns in <= 200 words. "
    "Preserve every URL fetched, every fact extracted, every tool name called, "
    "and any unresolved gaps. Output a concise bullet list. "
    "Do NOT include conversational filler."
)


Summarizer = Callable[[list[AgentMessage]], Awaitable[str]]
"""``async def(messages) -> str`` — caller provides this; usually wraps an LLM call."""


# ─── Cut-point selection ──────────────────────────────────────────────


def find_cut_point(
    messages: list[AgentMessage],
    keep_recent_tokens: int,
    model: str,
) -> int:
    """Return the index ``cut`` such that ``messages[cut:]`` keeps ≥keep_recent_tokens.

    Constraints:
    * ``cut`` MUST point at a user message (or be 0 when no compaction is
      possible).
    * Walking backwards from the end, accumulate tokens; once the budget is
      met AND the current index is a user message, return it.
    * If the entire transcript is < keep_recent_tokens, no cut is feasible →
      return 0 (caller treats as "nothing to compact").
    """
    if not messages:
        return 0

    accumulated = 0
    for idx in range(len(messages) - 1, -1, -1):
        msg_tokens = count_messages_tokens([messages[idx]], model)
        accumulated += msg_tokens
        if accumulated >= keep_recent_tokens and messages[idx].role == "user":
            return idx
    # Couldn't find a viable cut
    return 0


# ─── Trigger helper ──────────────────────────────────────────────────


def should_compact(
    state: AgentState,
    *,
    reserve_tokens: int = 4096,
    max_message_tokens: int | None = None,
) -> bool:
    """Return True when current transcript tokens exceed the safety threshold.

    Two triggers (either is sufficient):
    1. Context-window-relative: total > context_window(model) - reserve_tokens
    2. Absolute: total > max_message_tokens (when set). Guards budgets that are
       much smaller than the model's context window.
    """
    total = count_messages_tokens(state.messages, state.model)
    if max_message_tokens is not None and total > max_message_tokens:
        return True
    window = context_window(state.model)
    return total > window - reserve_tokens


# ─── Main entry point ────────────────────────────────────────────────


async def maybe_compact(
    state: AgentState,
    summarizer: Summarizer,
    *,
    reserve_tokens: int = 4096,
    keep_recent_tokens: int = 8000,
    max_message_tokens: int | None = None,
) -> bool:
    """Compact ``state.messages`` in-place if needed. Returns True if compacted."""
    if not should_compact(state, reserve_tokens=reserve_tokens, max_message_tokens=max_message_tokens):
        return False

    cut = find_cut_point(state.messages, keep_recent_tokens, state.model)
    if cut <= 0:
        # Either too short or no user message in the prefix to cut on.
        return False

    prefix = state.messages[:cut]
    if not prefix:
        return False

    prefix_tokens = count_messages_tokens(prefix, state.model)

    try:
        summary_text = await summarizer(prefix)
    except Exception as exc:
        logger.warning("compaction summarizer failed: %s", exc)
        return False

    if not isinstance(summary_text, str) or not summary_text.strip():
        logger.warning("compaction summarizer returned empty text; aborting")
        return False

    summary_msg = SummaryMessage(
        content=summary_text.strip(),
        summarized_count=cut,
        summarized_tokens=prefix_tokens,
    )

    state.messages = [summary_msg, *state.messages[cut:]]
    logger.info(
        "compacted %d messages (~%d tokens) into 1 summary (~%d tokens) [model=%s]",
        cut,
        prefix_tokens,
        count_tokens(summary_text, state.model),
        state.model,
    )
    return True


# ─── Default LLM-backed summarizer factory ────────────────────────────


def make_llm_summarizer(llm) -> Summarizer:
    """Convenience wrapper: build a summarizer from a langchain-style LLM.

    The LLM must expose ``await llm.ainvoke([SystemMessage, HumanMessage])``
    and return an object with a ``.content`` attribute.

    For tests, callers pass a custom callable directly to ``maybe_compact``.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    async def _summarize(messages: list[AgentMessage]) -> str:
        transcript = _format_transcript(messages)
        resp = await llm.ainvoke([
            SystemMessage(content=SUMMARY_SYSTEM_PROMPT),
            HumanMessage(content=transcript[:8000]),  # safety cap
        ])
        return getattr(resp, "content", str(resp))

    return _summarize


def _format_transcript(messages: list[AgentMessage]) -> str:
    """Pretty-print AgentMessages for the summariser."""
    parts: list[str] = []
    for m in messages:
        role = m.role
        content = (getattr(m, "content", "") or "")[:300]
        if role == "assistant":
            tcs = getattr(m, "tool_calls", None) or []
            if tcs:
                names = ", ".join(str(t.get("name", "?")) for t in tcs)
                parts.append(f"Assistant called: {names}")
            if content:
                parts.append(f"Assistant: {content}")
        elif role == "tool":
            tn = getattr(m, "tool_name", "?")
            parts.append(f"Tool({tn}): {content}")
        elif role == "user":
            parts.append(f"User: {content}")
        elif role == "summary":
            parts.append(f"[earlier summary]: {content}")
    return "\n".join(parts)
