"""WebHandler - LLM dispatch + context compaction + skill crystallization."""
from __future__ import annotations

import json
import logging
import re as _re
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool as _lc_tool

from agents.llm import get_llm as _get_llm, preserve_reasoning
from agents.web.prompts import build_system
from agents.web.tools import http as _http_tools
from agents.web.tools import parse as _parse_tools
from agents.web.tools.memory import recall_skill, save_skill

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


@_lc_tool
async def _ask_user_tool(question: str) -> str:
    """Ask user for clarification (cookies, captcha, intent)."""
    _emit(f"[ask_user] {question}", kind="info")
    return "[user input not collected in current run; assume default and continue]"


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
    _ask_user_tool,
]


def _all_tools(extra=None):
    out = list(_BASE_TOOLS)
    if extra:
        out.extend(extra)
    return out


class WebHandler:
    def __init__(self, url, intent, task_id=None, extra_tools=None, max_turns=20):
        self.url = url
        self.intent = intent
        self.task_id = task_id
        self.max_turns = max_turns
        self._tools = _all_tools(extra_tools)
        self._tool_map = {t.name: t for t in self._tools}
        self._llm = _get_llm()
        self._llm_bound = self._llm.bind_tools(self._tools)

    async def recall_skill_passive(self):
        try:
            return await recall_skill(query=self.intent, url=self.url)
        except Exception as exc:
            logger.debug("passive recall failed: %s", exc)
            return ""

    def build_system_prompt(self, skill_hint=""):
        return build_system(skill_hint)

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
        head = rest[:-6]
        tail = rest[-6:]
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
