"""WebHandler - LLM dispatch + context compaction + skill crystallization."""
from __future__ import annotations

import asyncio
import json
import logging
import re as _re
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool as _lc_tool

from agents.llm import get_llm as _get_llm, preserve_reasoning
from agents.web.prompts import build_system
from agents.web.tools import http as _http_tools
from agents.web.tools import parse as _parse_tools
from agents.web.tools.memory import recall_skill, save_skill

if TYPE_CHECKING:
    from agents.web.research_state import ResearchState

logger = logging.getLogger(__name__)


@dataclass
class StepOutcome:
    data: Any = None
    next_prompt: str | None = None
    should_exit: bool = False


def _emit(msg, kind="progress", task_id=None):
    try:
        from utils.agent_bus import emit
        emit(msg, kind=kind, agent="orchestrator", task_id=task_id)
    except Exception:
        pass


@_lc_tool
async def _recall_skill_tool(query: str = "", url: str = "") -> str:
    """Retrieve past successful recipes for similar URL/intent."""
    return await recall_skill(query=query, url=url)


@_lc_tool
async def _save_skill_tool(name: str, url_pattern: str, description: str, recipe: str) -> str:
    """Persist a successful execution path for future reuse."""
    sid = await save_skill(name=name, url_pattern=url_pattern, description=description, recipe=recipe)
    return f"saved skill {name} ({sid[:8]})"


_BASE_TOOLS = [
    _http_tools.http_get,
    _http_tools.http_get_batch,
    _http_tools.get_links,
    _http_tools.browser_get_text,
    _parse_tools.html_query,
    _parse_tools.regex_extract,
    _parse_tools.json_path,
    _parse_tools.text_search,
    _recall_skill_tool,
    _save_skill_tool,
]


def _all_tools(extra=None):
    out = list(_BASE_TOOLS)
    if extra:
        out.extend(extra)
    return out


class WebHandler:
    def __init__(
        self,
        url,
        intent,
        task_id=None,
        extra_tools=None,
        max_turns=20,
        research_state: "ResearchState | None" = None,
    ):
        self.url = url
        self.intent = intent
        self.task_id = task_id
        self.max_turns = max_turns
        self.research_state = research_state
        self._llm = _get_llm()

        handler_ref = self

        @_lc_tool
        async def self_check(intent: str, draft_record: str) -> dict:
            """Verify whether draft_record demonstrably satisfies intent.

            Returns {satisfied: bool, missing: list[str], suggested_next: str}.
            Call this BEFORE emitting your final record.
            """
            prompt = (
                f"Evaluate whether the draft record satisfies the user's intent.\n\n"
                f"Intent: {intent}\n\n"
                f"Draft record:\n{draft_record[:4000]}\n\n"
                f'Output STRICT JSON only, no prose: '
                f'{{"satisfied": true/false, "missing": ["specific gap 1", ...], '
                f'"suggested_next": "one short suggestion"}}\n'
                f"A record is satisfied only if it concretely addresses every implied "
                f"sub-question in the intent with cited information. Be strict but fair."
            )
            try:
                resp = await handler_ref._llm.ainvoke([
                    SystemMessage(content="You are a strict RAG record evaluator. Output JSON only."),
                    HumanMessage(content=prompt),
                ])
                import re as _re2, json as _json2
                m = _re2.search(r"\{[\s\S]*\}", resp.content)
                if not m:
                    return {"satisfied": False, "missing": ["self_check parse failed"], "suggested_next": "retry"}
                result = _json2.loads(m.group(0))
                # Auto-flip when satisfied: mark plan complete in research_state
                # so downstream tracking sees the run as verified.
                if isinstance(result, dict) and result.get("satisfied") is True:
                    if handler_ref.research_state is not None:
                        handler_ref.research_state.self_check_passed = True
                return result
            except Exception as exc:
                return {"satisfied": False, "missing": [f"self_check error: {exc}"], "suggested_next": "skip verification"}

        @_lc_tool
        async def record_fact(claim: str, source_url: str = "", confidence: float = 0.8) -> str:
            """Record a verified fact into research state.

            Call after extracting any concrete, citable piece of evidence so the
            auto-injected research-state reminder accumulates a fact ledger
            visible to every subsequent turn.
            """
            rs = handler_ref.research_state
            if rs is None:
                return "[no research_state attached]"
            try:
                rs.add_fact(claim=str(claim)[:400], source_url=str(source_url)[:300], confidence=float(confidence))
                return f"recorded fact ({len(rs.facts)} total)"
            except Exception as exc:
                return f"[record_fact error: {exc}]"

        @_lc_tool
        async def close_subgoal(subgoal: str) -> str:
            """Mark one of the planned subgoals as done.

            Use the exact subgoal string from the plan block. Matching is
            tolerant to surrounding whitespace.
            """
            rs = handler_ref.research_state
            if rs is None:
                return "[no research_state attached]"
            before = len(rs.open_subgoals)
            rs.close_subgoal(subgoal)
            after = len(rs.open_subgoals)
            if before == after:
                return f"[no matching open subgoal — current {after}]"
            return f"closed subgoal ({after} remaining)"

        @_lc_tool
        async def ask_user(question: str, timeout_seconds: int = 60) -> str:
            """Ask the user a clarification question and wait for their reply.

            Backed by the steering queue: the question is emitted as an
            agent event (kind="ask"); the user replies via POST
            /agent/{task_id}/steer kind=follow_up. Returns the user's
            answer or a timeout marker if no reply arrives in time.
            """
            tid = handler_ref.task_id
            if not tid:
                _emit(f"[ask_user] {question} (no task_id; cannot wait)", kind="info")
                return "[ask_user: no task_id wired; continuing without input]"

            # Surface the question to the UI / event log.
            _emit(f"[Q] {question}", kind="ask", task_id=tid)

            try:
                from agent_core import steering as _steering
            except ImportError:
                return "[ask_user: steering subsystem unavailable]"

            queues = _steering.get_queues(tid)
            if queues is None:
                return "[ask_user: task not registered with steering]"

            poll_interval = 0.5
            waited = 0.0
            max_wait = max(1.0, float(timeout_seconds))
            while waited < max_wait:
                drained = queues.follow_up.drain()
                if drained:
                    # Prefer the first follow-up; re-queue extras so they
                    # influence the next turn naturally.
                    answer = drained[0].content
                    for extra in drained[1:]:
                        await queues.follow_up.push(extra.content, priority=extra.priority)
                    return answer or "[ask_user: empty reply]"
                # Also accept normal steering messages as the answer.
                steers = queues.steering.drain()
                if steers:
                    answer = steers[0].content
                    for extra in steers[1:]:
                        await queues.steering.push(extra.content, priority=extra.priority)
                    return answer or "[ask_user: empty reply]"
                await asyncio.sleep(poll_interval)
                waited += poll_interval

            return f"[ask_user: no reply in {int(max_wait)}s; continuing without it]"

        base = _all_tools(extra_tools)
        self._tools = base + [self_check, record_fact, close_subgoal, ask_user]
        self._tool_map = {t.name: t for t in self._tools}
        self._llm_bound = self._llm.bind_tools(self._tools)

    async def recall_skill_passive(self):
        try:
            return await recall_skill(query=self.intent, url=self.url)
        except Exception as exc:
            logger.debug("passive recall failed: %s", exc)
            return ""

    def build_system_prompt(self, skill_hint="", analyst_hint=""):
        return build_system(skill_hint=skill_hint, analyst_hint=analyst_hint)

    async def llm_call(self, messages):
        return await self._llm_bound.ainvoke(preserve_reasoning(messages))

    async def dispatch(self, name, args):
        t = self._tool_map.get(name)
        if t is None:
            return StepOutcome(
                data=f"[unknown tool: {name}]",
                next_prompt=f"Tool {name!r} not available.",
            )
        try:
            if hasattr(t, "ainvoke"):
                result = await t.ainvoke(args)
            else:
                result = t.invoke(args)
            return StepOutcome(data=result)
        except Exception as exc:
            logger.warning("tool %s error: %s", name, exc)
            return StepOutcome(data=f"[{name} error: {exc}]")

    async def compact(self, messages):
        if len(messages) < 12:
            return messages
        sys_msgs = [m for m in messages if isinstance(m, SystemMessage)]
        rest = [m for m in messages if not isinstance(m, SystemMessage)]
        if len(rest) < 8:
            return messages

        # ── Safe cut point: anchor on a HumanMessage so the resulting tail
        # never starts with an orphan ToolMessage (which DeepSeek/OpenAI
        # reject with 400 "tool must be a response to preceding tool_calls").
        # Walk backwards from len(rest)-6 to find the latest HumanMessage.
        target_keep = 6
        cut_idx = None
        start = max(0, len(rest) - target_keep)
        for i in range(start, -1, -1):
            if isinstance(rest[i], HumanMessage):
                cut_idx = i
                break
        if cut_idx is None or cut_idx == 0:
            # No prior user turn to summarise — skip compaction this round.
            return messages

        head = rest[:cut_idx]
        tail = rest[cut_idx:]
        try:
            transcript = []
            for m in head:
                if isinstance(m, AIMessage):
                    if getattr(m, "tool_calls", None):
                        names = ", ".join(tc["name"] for tc in m.tool_calls)
                        transcript.append(f"Assistant called: {names}")
                    if m.content:
                        transcript.append(f"Assistant: {str(m.content)[:300]}")
                elif isinstance(m, ToolMessage):
                    transcript.append(f"Tool result: {str(m.content)[:300]}")
                elif isinstance(m, HumanMessage):
                    transcript.append(f"Human: {str(m.content)[:300]}")
            joined = chr(10).join(transcript)[:6000]
            summary_resp = await self._llm.ainvoke(preserve_reasoning([
                SystemMessage(content="Summarise progress in <=200 words. Include URLs, findings, gaps."),
                HumanMessage(content=joined),
            ]))
            summary = summary_resp.content
        except Exception as exc:
            logger.debug("compact summariser failed: %s", exc)
            summary = "[earlier turns truncated]"
        compacted = HumanMessage(content="## Earlier turns (compacted)" + chr(10) + str(summary))
        return sys_msgs + [compacted] + tail

    async def maybe_crystallize(self, messages, outcome_data):
        tool_calls_made = sum(
            len(getattr(m, "tool_calls", []) or [])
            for m in messages if isinstance(m, AIMessage)
        )
        if tool_calls_made < 4:
            return None
        try:
            transcript = []
            for m in messages[-20:]:
                if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
                    for tc in m.tool_calls:
                        args_str = json.dumps(tc.get("args", {}), ensure_ascii=False)[:200]
                        transcript.append(f"called {tc['name']}({args_str})")
            joined = chr(10).join(transcript)[:3000]
            schema_hint = (
                "Output ONLY a JSON object with keys: name (short id), "
                "url_pattern (regex), description (one line), recipe (numbered steps). "
                "url_pattern should match URLs of the same kind. Generalise the original URL."
            )
            resp = await self._llm.ainvoke(preserve_reasoning([
                SystemMessage(content="Extract a reusable recipe. " + schema_hint),
                HumanMessage(content="URL: " + str(self.url) + chr(10) + "Intent: " + str(self.intent) + chr(10) + "Calls:" + chr(10) + joined),
            ]))
            m = _re.search(r"\{[\s\S]*\}", resp.content)
            if not m:
                return None
            data = json.loads(m.group(0))
            sid = await save_skill(
                name=str(data.get("name", "auto"))[:60],
                url_pattern=str(data.get("url_pattern", ""))[:300],
                description=str(data.get("description", ""))[:300],
                recipe=str(data.get("recipe", ""))[:4000],
            )
            return sid
        except Exception as exc:
            logger.debug("crystallize failed: %s", exc)
            return None
