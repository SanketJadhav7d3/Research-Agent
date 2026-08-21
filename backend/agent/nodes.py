"""The five graph nodes.

Each takes the current state and returns only the keys it changed; LangGraph
merges the result. Nodes read their model through get_model() so the provider
stays swappable.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from config import (
    MAX_MODEL_TURNS_CAP,
    MAX_TOOL_CALLS_PER_ROUND,
    MAX_TOOL_CALLS_TOTAL,
)
from agent.events import emit
from agent.llm import get_model
from agent.schemas import ClarifiedGoal, Reflection, ResearchPlan
from agent.state import AgentState
from agent.tools import ALL_TOOLS, TOOLS_BY_NAME

log = logging.getLogger(__name__)

# Per-finding character allowances when rendering evidence for the model.
SNIPPET_CHARS = 1_200
DOC_CHARS = 8_000


def _evidence(findings: list[dict]) -> str:
    """Render findings for the model.

    Documents the agent chose to open get a far larger allowance than search
    snippets it merely received.

    Includes the actual content, not just the claim line: a page read stores
    thousands of characters in `snippet`, and reasoning from the claim alone
    ("Full text of <url>") throws away everything that was fetched. Each item is
    truncated so one long page cannot crowd out the rest.
    """
    parts = []
    for i, f in enumerate(findings, 1):
        body = (f.get("snippet") or "").strip()
        # A fetched document is the reason we fetched it; a search snippet is a
        # preview. Giving both the same allowance throws away most of a PDF.
        limit = DOC_CHARS if f.get("pages") or f.get("truncated") is not None else SNIPPET_CHARS
        if len(body) > limit:
            body = body[:limit] + " [...]"
        parts.append(
            f"[{i}] {f.get('title') or f.get('claim')} - {f.get('url')}\n{body}"
        )
    return "\n\n".join(parts)


def _text(response) -> str:
    """Flatten a model response to plain text.

    Newer models return content as a list of typed parts rather than a string;
    interpolating that directly would put Python repr into the report.
    """
    content = response.content
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts)


def _model(state: AgentState):
    """Model for this run, honouring any per-request provider override."""
    return get_model(
        provider=state.get("provider") or None,
        model=state.get("model") or None,
        api_key=state.get("api_key") or None,
    )


def clarify(state: AgentState) -> dict:
    """Restate the goal precisely and surface the assumptions being made."""
    emit("node_start", node="clarify")
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
    emit("node_start", node="plan")
    result = _model(state).with_structured_output(ResearchPlan).invoke(
        "Break this research goal into 3-5 concrete sub-questions. Each must be "
        "independently researchable, and together they must fully cover the "
        "goal. Do not answer them.\n\n"
        f"Goal: {state['clarified_goal']}"
    )
    log.info("planned %d sub-questions", len(result.sub_questions))
    return {"plan": result.sub_questions}


def _call_key(tool_name: str, args: dict) -> str:
    """Identity of a tool call, for spotting repeats.

    URLs are normalised so trivially different spellings of the same address
    (trailing slash, arxiv's optional .pdf suffix) count as one fetch.
    """
    parts = []
    for key in sorted(args):
        value = str(args[key]).strip()
        if value.startswith(("http://", "https://")):
            value = value.rstrip("/")
            if value.endswith(".pdf"):
                value = value[:-4]
        parts.append(f"{key}={value.lower()}")
    return tool_name + "|" + "&".join(parts)


def _execute_brief(state: AgentState) -> str:
    """The instruction for one round of research.

    On the first round this is the plan. On a later round the agent has already
    judged its own work, so the brief becomes the gaps it identified plus the
    queries it has already tried — otherwise it tends to reissue the same
    searches and learn nothing new.
    """
    goal = state["clarified_goal"]
    gaps = state.get("gaps") or []

    if state.get("iteration", 0) == 0 or not gaps:
        return (
            f"Research goal: {goal}\n\n"
            "Sub-questions identified during planning:\n"
            + "\n".join(f"- {q}" for q in state["plan"])
        )

    tried = [
        str(v)
        for c in state.get("tool_calls", [])
        for v in (c.get("input") or {}).values()
    ]
    return (
        f"Research goal: {goal}\n\n"
        f"You already researched this and judged it incomplete "
        f"(confidence {state.get('confidence', 0):.0%}). "
        f"{state.get('confidence_reason', '')}\n\n"
        "Fill these specific gaps:\n"
        + "\n".join(f"- {g}" for g in gaps)
        + "\n\nQueries you already tried — do not repeat them. Rephrase, "
          "narrow, or approach from a different angle:\n"
        + "\n".join(f"- {t}" for t in tried[-15:])
    )


def execute(state: AgentState) -> dict:
    """The free node — the model drives its own research.

    Rather than walking the plan mechanically, the model is given every tool and
    decides what to call, in what order, and when it has enough. It may skip
    sub-questions, chase leads the plan never mentioned, call one tool many
    times, or call several at once. The loop ends when the model stops asking
    for tools; the caps are a safety net, not the expected exit.
    """
    emit("node_start", node="execute")
    model = _model(state).bind_tools(ALL_TOOLS)

    messages: list = [
        SystemMessage(
            "You are a research agent gathering evidence.\n\n"
            "You have tools available. Decide for yourself which to use and in "
            "what order — the plan below is guidance, not a checklist. Skip "
            "parts already answered, follow up on anything interesting, and "
            "pursue questions the plan missed if they matter.\n\n"
            "If the goal names a specific URL, fetch it — read_pdf for a PDF, "
            "read_page otherwise. Searching for a document you were handed the "
            "address of wastes a call and returns worse evidence than the "
            "source itself.\n\n"
            "Search snippets are short and often superficial. When a result "
            "looks central to the question, open it rather than relying on the "
            "preview.\n\n"
            "Call tools in parallel when the queries are independent. Stop "
            "calling tools once you have enough evidence, and then briefly "
            "summarise what you found and what is still missing."
        ),
        HumanMessage(_execute_brief(state)),
    ]

    tool_calls = list(state.get("tool_calls", []))
    findings = list(state.get("findings", []))
    stopped_early = False

    # Budget for this round: the per-round allowance, or whatever remains of the
    # overall ceiling, whichever is smaller.
    calls_before = len(tool_calls)
    budget = min(MAX_TOOL_CALLS_PER_ROUND, MAX_TOOL_CALLS_TOTAL - calls_before)

    # Calls already made, including in earlier rounds of this run. Fetching the
    # same document repeatedly spends budget and adds nothing.
    seen_calls = {_call_key(c["tool"], c.get("input") or {}) for c in tool_calls}
    seen_urls = {f.get("url") for f in findings if f.get("url")}

    for turn in range(MAX_MODEL_TURNS_CAP):
        response = model.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            log.info("model finished after %d turn(s)", turn + 1)
            break

        # Run this turn's tool calls concurrently. Page reads take seconds, so
        # doing them one after another would dominate the run time.
        runnable = []
        for call in response.tool_calls:
            if len(runnable) + len(tool_calls) - calls_before >= budget:
                stopped_early = True
                break

            tool = TOOLS_BY_NAME.get(call["name"])
            if tool is None:
                # Shouldn't happen, but a hallucinated name must not crash the run.
                log.warning("unknown tool %r", call["name"])
                messages.append(ToolMessage(
                    content=f"No such tool: {call['name']}",
                    tool_call_id=call["id"],
                ))
                continue

            key = _call_key(call["name"], call["args"])
            if key in seen_calls:
                log.info("skipping repeat: %s(%s)", call["name"], call["args"])
                emit("tool_skipped", tool=call["name"], input=call["args"],
                     reason="already fetched in this run")
                messages.append(ToolMessage(
                    content="You already made this exact call in this run. Its "
                            "results are above — use them rather than fetching "
                            "again, or try a different query.",
                    tool_call_id=call["id"],
                ))
                continue
            seen_calls.add(key)

            log.info("tool: %s(%s)", call["name"], call["args"])
            # Emitted from this thread: the stream writer is not visible inside
            # worker threads.
            emit("tool_call", tool=call["name"], input=call["args"])
            runnable.append((call, tool))

        if runnable:
            with ThreadPoolExecutor(max_workers=len(runnable)) as pool:
                futures = {
                    pool.submit(t.invoke, c["args"]): c for c, t in runnable
                }
                outcomes = []
                for future in as_completed(futures):
                    call = futures[future]
                    try:
                        outcomes.append((call, future.result()))
                    except Exception as exc:  # noqa: BLE001 - reported to the model
                        log.warning("tool %s raised: %s", call["name"], exc)
                        outcomes.append((call, [{
                            "claim": f"{call['name']} failed",
                            "snippet": str(exc), "url": "",
                            "title": "Tool error", "error": True,
                        }]))

            # Append in the model's original order so the transcript matches the
            # order it asked for, regardless of which finished first.
            order = {id(c): i for i, (c, _) in enumerate(runnable)}
            for call, results in sorted(outcomes, key=lambda o: order[id(o[0])]):
                emit(
                    "tool_result",
                    tool=call["name"],
                    result_count=len(results),
                    sources=[
                        {"url": r.get("url"), "title": r.get("title")}
                        for r in results if r.get("url")
                    ],
                )
                tool_calls.append({
                    "tool": call["name"],
                    "input": call["args"],
                    "result_count": len(results),
                })
                fresh = [
                    r for r in results
                    if not r.get("url") or r["url"] not in seen_urls
                ]
                seen_urls.update(r["url"] for r in fresh if r.get("url"))
                findings.extend(fresh)
                messages.append(ToolMessage(
                    content=json.dumps(results), tool_call_id=call["id"]
                ))

        if stopped_early:
            log.warning("round tool budget (%d) spent", budget)
            break
    else:
        stopped_early = True
        log.warning("model turn cap (%d) reached", MAX_MODEL_TURNS_CAP)

    return {
        "tool_calls": tool_calls,
        "findings": findings,
        "stopped_early": stopped_early,
        "iteration": state.get("iteration", 0) + 1,
    }
def reflect(state: AgentState) -> dict:
    """Score how well the findings actually answer the goal."""
    emit("node_start", node="reflect")
    evidence = _evidence(state["findings"])
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
    emit(
        "confidence_check",
        score=result.confidence,
        reason=result.reason,
        gaps=result.gaps,
        loop=state.get("iteration", 0),
    )
    return {
        "confidence": result.confidence,
        "confidence_reason": result.reason,
        "gaps": result.gaps,
    }


def synthesize(state: AgentState) -> dict:
    """Write the final cited report."""
    emit("node_start", node="synthesize")
    citations = []
    seen = set()
    for f in state["findings"]:
        if f["url"] not in seen:
            seen.add(f["url"])
            citations.append({"url": f["url"], "title": f["title"]})

    numbered = "\n".join(
        f"[{i + 1}] {c['title']} - {c['url']}" for i, c in enumerate(citations)
    )
    evidence = _evidence(state["findings"])

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

    report = f"{_text(response)}\n\n## Sources\n\n{numbered}\n"
    emit(
        "report_ready",
        report=report,
        citations=citations,
        total_tool_calls=len(state.get("tool_calls", [])),
        loops=state.get("iteration", 0),
    )
    return {"report": report, "citations": citations}
