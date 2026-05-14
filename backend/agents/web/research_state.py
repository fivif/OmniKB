"""ResearchState — explicit exploration state injected as a system reminder each turn.

The web agent traditionally relies on message history for memory. Long sessions
let key facts drift out of attention. This dataclass captures the structured
exploration state (visited URLs, collected facts, open subgoals, tool usage)
and renders a compact reminder appended to the LLM context each turn.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Fact:
    claim: str
    source_url: str
    confidence: float = 0.8


@dataclass
class ResearchState:
    visited_urls: set[str] = field(default_factory=set)
    facts: list[Fact] = field(default_factory=list)
    open_subgoals: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    attempted_tools: dict[str, int] = field(default_factory=dict)
    plan_locked: bool = False
    self_check_passed: bool = False

    def mark_visited(self, url: str) -> None:
        if url:
            self.visited_urls.add(url)

    def add_fact(self, claim: str, source_url: str, confidence: float = 0.8) -> None:
        self.facts.append(Fact(claim=claim, source_url=source_url, confidence=confidence))

    def record_tool(self, name: str) -> None:
        self.attempted_tools[name] = self.attempted_tools.get(name, 0) + 1

    def lock_plan(self, subgoals: list[str], criteria: list[str]) -> None:
        self.open_subgoals = list(subgoals)
        self.success_criteria = list(criteria)
        self.plan_locked = True

    def close_subgoal(self, subgoal: str) -> None:
        self.open_subgoals = [g for g in self.open_subgoals if g.strip() != subgoal.strip()]

    def to_reminder(self, max_chars: int = 900) -> str:
        """Compact reminder for system injection each turn.

        Returns empty string if the agent has not yet started exploring (no plan, no fetches).
        """
        if not self.plan_locked and not self.visited_urls:
            return ""
        lines = ["## Research state (auto-injected)"]
        if self.success_criteria:
            lines.append("Success criteria:")
            for c in self.success_criteria[:6]:
                lines.append(f"  ✓ {c}")
        if self.open_subgoals:
            lines.append(f"Open subgoals ({len(self.open_subgoals)}):")
            for g in self.open_subgoals[:8]:
                lines.append(f"  • {g}")
        if self.visited_urls:
            urls = list(self.visited_urls)
            shown = urls[:6]
            lines.append(f"Visited URLs ({len(urls)}): " + ", ".join(shown))
            if len(urls) > 6:
                lines[-1] += f" ... +{len(urls)-6} more"
        if self.facts:
            lines.append(f"Facts collected ({len(self.facts)}):")
            for f in self.facts[-6:]:
                lines.append(f"  - {f.claim} [{f.source_url[:60]}]")
        if self.attempted_tools:
            ranked = sorted(self.attempted_tools.items(), key=lambda x: -x[1])[:8]
            tools = ", ".join(f"{k}×{v}" for k, v in ranked)
            lines.append(f"Tools used: {tools}")
        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n...[truncated]"
        return text
