"""OmniKB Agent Core — provider-agnostic agent runtime.

This package is intentionally decoupled from any specific LLM provider, tool
implementation, or business domain. It mirrors the architecture of
`pi-agent-core` (earendil-works/pi) but in async Python.

Public surface:
    AgentState           — runtime state container
    AgentMessage         — union of user / assistant / tool / summary messages
    AgentEvent           — typed lifecycle event (added in M1.3)
    EventStream          — broadcast async event bus  (added in M1.3)
    ToolDefinition       — declarative tool registration
    ToolExecutor         — parallel/sequential dispatch
    Hooks                — convertToLlm + interception hooks
    run_loop             — main turn loop                (added in Layer 3)
"""
from __future__ import annotations

from .state import AgentState
from .messages import (
    AgentMessage,
    UserMessage,
    AssistantMessage,
    ToolMessage,
    SummaryMessage,
)

__all__ = [
    "AgentState",
    "AgentMessage",
    "UserMessage",
    "AssistantMessage",
    "ToolMessage",
    "SummaryMessage",
]
