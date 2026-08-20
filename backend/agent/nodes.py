"""The five graph nodes.

Each takes the current state and returns only the keys it changed; LangGraph
merges the result. Nodes read their model through get_model() so the provider
stays swappable.
"""

import logging

from config import MAX_TOOL_CALLS_CAP
from agent.llm import get_model
from agent.schemas import ClarifiedGoal, Reflection, ResearchPlan
from agent.state import AgentState
from agent.tools.mock import mock_search

log = logging.getLogger(__name__)


def _model(state: AgentState):
    """Model for this run. Per-request provider overrides arrive in Sprint 4."""
    return get_model()


def clarify(state: AgentState) -> dict:
    """Restate the goal precisely and surface the assumptions being made."""
    result = _model(state).with_structured_output(ClarifiedGoal).invoke(
        "You are scoping a research task. Restate the goal below precisely: make "
        "the scope, timeframe and subject explicit, and resolve any ambiguity. "
        "List the assumptions you had to make.\n\n"
        f"Goal: {state['goal']}"
    )
    log.info("clarified: %s", result.clarified_goal)
    return {
        "clarified_goal": result.clarified_goal,
        "assumptions": result.assumptions,
    }


def plan(state: AgentState) -> dict:
    """Break the goal into independently researchable sub-questions."""
    result = _model(state).with_structured_output(ResearchPlan).invoke(
        "Break this research goal into 3-5 concrete sub-questions. Each must be "
        "independently researchable, and together they must fully cover the "
        "goal. Do not answer them.\n\n"
        f"Goal: {state['clarified_goal']}"
    )
    log.info("planned %d sub-questions", len(result.sub_questions))
    return {"plan": result.sub_questions}


def execute(state: AgentState) -> dict:
    """Gather evidence for each sub-question.

    Sprint 2 walks the plan and calls the mock tool for each sub-question. From
    Sprint 3 the model chooses which tool to call per sub-question; the caps
    below stay regardless.
    """
    tool_calls = list(state.get("tool_calls", []))
    findings = list(state.get("findings", []))

    for question in state["plan"]:
        if len(tool_calls) >= MAX_TOOL_CALLS_CAP:
            log.warning("tool call cap (%d) reached; stopping early", MAX_TOOL_CALLS_CAP)
            break

        results = mock_search(question)
        tool_calls.append(
            {"tool": "mock_search", "input": question, "result_count": len(results)}
        )
        findings.extend(results)

    return {
        "tool_calls": tool_calls,
        "findings": findings,
        "iteration": state.get("iteration", 0) + 1,
    }


def reflect(state: AgentState) -> dict:
    """Score how well the findings actually answer the goal."""
    evidence = "\n".join(
        f"- {f['claim']} (source: {f['url']})" for f in state["findings"]
    )
    result = _model(state).with_structured_output(Reflection).invoke(
        "Assess honestly whether the evidence below answers the research goal. "
        "Be critical: score low if sources are thin, irrelevant or fabricated. "
        "Note that placeholder or mock evidence does not genuinely answer "
        "anything.\n\n"
        f"Goal: {state['clarified_goal']}\n\n"
        f"Sub-questions:\n" + "\n".join(f"- {q}" for q in state["plan"]) + "\n\n"
        f"Evidence:\n{evidence}"
    )
    log.info("confidence %.2f - %s", result.confidence, result.reason)
    return {
        "confidence": result.confidence,
        "confidence_reason": result.reason,
        "gaps": result.gaps,
    }


def synthesize(state: AgentState) -> dict:
    """Write the final cited report."""
    citations = []
    seen = set()
    for f in state["findings"]:
        if f["url"] not in seen:
            seen.add(f["url"])
            citations.append({"url": f["url"], "title": f["title"]})

    numbered = "\n".join(
        f"[{i + 1}] {c['title']} - {c['url']}" for i, c in enumerate(citations)
    )
    evidence = "\n".join(
        f"- {f['claim']} (source: {f['url']})" for f in state["findings"]
    )

    response = _model(state).invoke(
        "Write a markdown research report answering the goal, using only the "
        "evidence below. Cite sources inline as [1], [2] matching the list. Do "
        "not invent facts. State limitations plainly where the evidence is weak "
        "or is placeholder data. Do not include a sources section — it is "
        "appended for you.\n\n"
        f"Goal: {state['clarified_goal']}\n\n"
        f"Confidence: {state['confidence']:.2f} ({state['confidence_reason']})\n\n"
        f"Evidence:\n{evidence}\n\n"
        f"Sources:\n{numbered}"
    )

    report = f"{response.content}\n\n## Sources\n\n{numbered}\n"
    return {"report": report, "citations": citations}
