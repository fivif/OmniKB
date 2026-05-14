"""AgentState — runtime state container for one agent run.

The state is a plain dataclass; all mutations happen explicitly inside
``run_loop`` (M1.3 / Layer 3) so that lifecycle events stay trivially
traceable. No methods on this class — keep it dumb on purpose.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .messages import AgentMessage


@dataclass
class AgentState:
    """Single source of truth for one agent execution.

    Field names mirror pi-agent-core's ``AgentState``
    (see earendil-works/pi packages/agent/src/agent.ts).
    """

    # Required at construction
    system_prompt: str
    model: str

    # Mutable conversation transcript
    messages: list["AgentMessage"] = field(default_factory=list)

    # Runtime flags (set/reset by the loop)
    is_streaming: bool = False
    pending_tool_calls: set[str] = field(default_factory=set)
    error_message: str | None = None
    turn: int = 0

    # Terminal classification set by ``run_loop`` right before returning.
    # One of: ``"running"`` (still inside the loop), ``"completed"``,
    # ``"max_turns"``, ``"budget_exceeded"``, ``"aborted"``, ``"failed"``.
    # Callers can inspect this to distinguish a clean exit from an early
    # termination caused by caps, cancellation, or LLM failure.
    final_status: str = "running"

    # Metadata for cross-system correlation
    task_id: str | None = None
    session_id: str | None = None
