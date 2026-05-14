"""AgentMessage types — OmniKB's canonical conversation records.

These are the *internal* representation. The :class:`Hooks.convert_to_llm`
hook is responsible for translating between this and whatever the active
LLM provider expects (LangChain BaseMessage / OpenAI dict / Anthropic
content blocks / etc.).

Designed to be JSON-serialisable via :func:`dataclasses.asdict`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Union


@dataclass
class UserMessage:
    """A user-authored prompt or steering injection."""
    content: str = ""
    timestamp: float = 0.0
    role: Literal["user"] = "user"


@dataclass
class AssistantMessage:
    """LLM output. May contain prose, tool_calls, and reasoning."""
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    """Each entry: ``{"tool_call_id": str, "name": str, "args": dict}``."""
    thinking: str | None = None
    """Reasoning trace from reasoning models (DeepSeek-R1, Claude w/thinking)."""
    timestamp: float = 0.0
    role: Literal["assistant"] = "assistant"


@dataclass
class ToolMessage:
    """Result of one tool invocation. Content is LLM-facing (truncated)."""
    tool_call_id: str = ""
    tool_name: str = ""
    content: str = ""
    """Truncated preview meant for the LLM (≤ DEFAULT_MAX_BYTES)."""
    full_log_path: str | None = None
    """Path to the un-truncated output, if it overflowed."""
    timestamp: float = 0.0
    role: Literal["tool"] = "tool"


@dataclass
class SummaryMessage:
    """Inserted at the head after compaction; replaces summarised history."""
    content: str = ""
    """LLM-generated summary (≤ ~300 tokens)."""
    summarized_count: int = 0
    """Number of original messages this summary replaces."""
    summarized_tokens: int = 0
    """Approximate token count of the original messages."""
    timestamp: float = 0.0
    role: Literal["summary"] = "summary"


AgentMessage = Union[UserMessage, AssistantMessage, ToolMessage, SummaryMessage]
