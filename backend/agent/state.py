"""State passed between graph nodes.

LangGraph merges each node's returned dict into this object, so a node only
returns the keys it actually changed.
"""

from typing import TypedDict


class AgentState(TypedDict, total=False):
    goal: str                   # Original research goal, as the user typed it
    clarified_goal: str         # Scoped and disambiguated restatement
    assumptions: list[str]      # Ambiguities the agent resolved on its own
    plan: list[str]             # Sub-questions to answer
    tool_calls: list[dict]      # Record of every tool call made
    findings: list[dict]        # Structured findings with sources
    confidence: float           # 0.0-1.0 self-assessed confidence
    confidence_reason: str      # Why the agent rated it that way
    gaps: list[str]             # Sub-questions still weakly answered
    iteration: int              # Execute -> reflect loops completed
    max_iterations: int         # Hard cap
    stopped_early: bool         # True if a safety cap ended Execute, not the model
    report: str                 # Final markdown report
    citations: list[dict]       # Sources referenced by the report
