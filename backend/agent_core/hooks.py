"""Hooks — pluggable interception points for the agent loop.

Mirrors pi-agent-core's hook contract:
* ``convert_to_llm`` (REQUIRED) — translate ``AgentMessage`` to provider format.
* ``transform_context`` — last-chance message-list mutation before LLM call.
* ``before_tool_call`` — block or modify a tool invocation.
* ``after_tool_call`` — post-process a tool result (e.g. truncate).

Why these four?
The loop has four explicit injection points — exactly these. Anything else
belongs in tools or in the convert_to_llm bridge.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .messages import AgentMessage
    from .tool import ToolResult


# Required: AgentMessage[] -> provider-native message list (e.g. OpenAI dict).
ConvertToLlm = Callable[[list["AgentMessage"]], list[dict[str, Any]]]

# Optional: prune / re-shape messages before they hit convert_to_llm.
TransformContext = Callable[[list["AgentMessage"]], list["AgentMessage"]]

# Optional: returned dict of {"block": True, "reason": ...} blocks one tool;
# returning None / {} lets it run.
BeforeToolCall = Callable[
    [str, dict[str, Any]],
    Awaitable[dict[str, Any] | None],
]

# Optional: post-process a ToolResult (mutate or replace).
AfterToolCall = Callable[
    [str, dict[str, Any], "ToolResult"],
    Awaitable["ToolResult"],
]


@dataclass
class Hooks:
    """Plug-in container for the agent loop's four extension points."""
    convert_to_llm: ConvertToLlm
    """REQUIRED — translates internal AgentMessage list to provider format."""

    transform_context: TransformContext | None = None
    before_tool_call: BeforeToolCall | None = None
    after_tool_call: AfterToolCall | None = None
