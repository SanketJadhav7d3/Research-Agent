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
    MAX_SANDBOX_CALLS,
    MAX_CHARTS,
)
from agent import keywords, sandbox_client
from agent.events import emit
from agent.llm import get_model
from agent.schemas import ClarifiedGoal, Reflection, ResearchPlan
from agent.state import AgentState
from agent.tools import ALL_TOOLS, TOOLS_BY_NAME
from agent.tools.code import make_run_python

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
    prefs = keywords.brief(
        state.get("include_keywords") or [], state.get("exclude_keywords") or []
    )

    if state.get("iteration", 0) == 0 or not gaps:
        return (
            f"Research goal: {goal}\n\n"
            "Sub-questions identified during planning:\n"
            + "\n".join(f"- {q}" for q in state["plan"])
            + prefs
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
        + prefs
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

    include = state.get("include_keywords") or []
    exclude = state.get("exclude_keywords") or []

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

            # Fold the user's required terms into the query before dedup, so
            # the recorded call and the trace show what was actually searched.
            if include and call["name"] in keywords.SEARCH_TOOLS:
                query = call["args"].get("query")
                if isinstance(query, str):
                    call["args"]["query"] = keywords.augment(query, include)

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
                # Enforce the user's exclusions on search results only. A page
                # or PDF the model deliberately opened is not filtered — it
                # asked for that specific document.
                dropped = 0
                if exclude and call["name"] in keywords.SEARCH_TOOLS:
                    results, dropped = keywords.filter_results(results, exclude)
                    if dropped:
                        log.info("excluded %d result(s) from %s", dropped, call["name"])
                        emit("results_filtered", tool=call["name"],
                             dropped=dropped, terms=exclude)

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
                # Say so when the filter emptied a result set, or the model
                # sees a bare [] and concludes the topic has no coverage.
                content = json.dumps(results)
                if dropped:
                    content += (
                        f"\n\nNote: {dropped} result(s) were removed because they "
                        f"mention terms the user excluded ({', '.join(exclude)}). "
                        f"Try a query that approaches the question from a "
                        f"different angle."
                    )
                messages.append(ToolMessage(content=content, tool_call_id=call["id"]))

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

    charts = state.get("charts") or []
    chart_brief = ""
    if charts:
        listed = "\n".join(
            f"[chart:{i}] {c.get('title') or 'untitled'}"
            for i, c in enumerate(charts, 1)
        )
        chart_brief = (
            f"\n\nCharts drawn from this evidence:\n{listed}\n\n"
            "Place each marker alone on its own line where the chart belongs, with "
            "nothing after it — the title and figure number are rendered for "
            "you, so repeating them reads as a duplicate. Explain in the "
            "surrounding prose what the chart shows. Use every marker exactly "
            "once, and invent no others.\n"
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
        f"{chart_brief}"
    )

    report = f"{_text(response)}\n\n## Sources\n\n{numbered}\n"
    emit(
        "report_ready",
        report=report,
        citations=citations,
        charts=charts,
        total_tool_calls=len(state.get("tool_calls", [])),
        loops=state.get("iteration", 0),
    )
    return {"report": report, "citations": citations}


VISUALIZE_SYSTEM = (
    "You turn research evidence into charts.\n\n"
    "You have one tool: run_python. The evidence is already loaded there as a "
    "variable called `findings`.\n\n"
    "The brief below names which findings carry a `data` dict and which keys "
    "it holds. When it does, go straight to plotting — no inspection call is "
    "needed. Inspect only when you must parse figures out of ['text'], and "
    "then print keys, lengths and types rather than the values themselves.\n\n"
    "You have very few calls, and each result tells you how many remain.\n\n"
    "The environment is already prepared. pandas, numpy, plotly and matplotlib "
    "are installed and importable. Never spend a call checking versions, "
    "testing imports, or confirming the environment works.\n\n"
    "Read every number out of `findings` in code — parse the text, or use the "
    "`data` dict where a finding has one. Do not retype figures as literals in "
    "your plotting code. A number you typed by hand is a number you can get "
    "wrong, and a wrong number drawn as a clean chart is more convincing than "
    "the same mistake in a sentence.\n\n"
    "Most research questions have nothing worth charting. Producing no chart "
    "is the correct answer unless the evidence contains real numeric series or "
    "genuinely comparable figures. Never manufacture, estimate or interpolate "
    "data to fill a chart — a plausible-looking chart of invented numbers is "
    "far worse than no chart.\n\n"
    "Chart only what a reader would gain from seeing: a trend over time, a "
    "comparison across entities, a breakdown of a total. At most three charts. "
    "Give each a clear title and axis labels.\n\n"
    "When you are done, or if there is nothing to chart, stop calling tools and "
    "say so in one sentence."
)


def _visualize_brief(state: AgentState) -> str:
    """What the model is shown before it decides whether to chart anything.

    Titles and sources only. The numbers stay in the sandbox, which is the
    whole point — the model writes code that reads them, so it never has the
    opportunity to transcribe one wrongly.
    """
    lines = []
    structured = 0
    for i, f in enumerate(state["findings"], 1):
        if f.get("error"):
            continue
        title = f.get("title") or f.get("claim")
        note = ""
        # Naming the keys — never the values — is what removes the excuse to
        # print the data and then retype it. The model can index straight in.
        if isinstance(f.get("data"), dict) and f["data"]:
            structured += 1
            note = f"  -> findings[{i - 1}]['data'] has: {', '.join(sorted(f['data']))}"
        elif f.get("pages"):
            note = f"  -> {f['pages']}pp document, figures are in ['text']"
        lines.append(f"[{i}] {title}" + (f"\n{note}" if note else ""))

    hint = (
        f"\n\n{structured} finding(s) carry a ready-made `data` dict. Chart "
        f"from those directly — no parsing and no inspection call needed."
        if structured else
        "\n\nNo finding carries structured data, so any figures must be parsed "
        "out of ['text'] in code."
    )

    return (
        f"Research goal: {state['clarified_goal']}\n\n"
        f"Evidence in `findings` (values are in the sandbox, deliberately not "
        f"shown here):\n" + "\n".join(lines) + hint
    )


def visualize(state: AgentState) -> dict:
    """Let the model write code to chart the evidence, if anything warrants it.

    Runs after the confidence gate rather than inside the research loop:
    charting mid-loop spends sandbox calls on evidence a later round may
    replace.
    """
    if not sandbox_client.available() or not state.get("findings"):
        return {}

    emit("node_start", node="visualize")

    charts: list[dict] = []
    run_python = make_run_python(state["findings"], charts)
    model = _model(state).bind_tools([run_python])

    messages: list = [
        SystemMessage(VISUALIZE_SYSTEM),
        HumanMessage(_visualize_brief(state)),
    ]

    calls = 0
    for _ in range(MAX_SANDBOX_CALLS + 1):
        response = model.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            break

        for call in response.tool_calls:
            if calls >= MAX_SANDBOX_CALLS:
                messages.append(ToolMessage(
                    content="No execution attempts remain. Stop here.",
                    tool_call_id=call["id"],
                ))
                continue

            calls += 1
            purpose = call["args"].get("purpose") or "analysis"
            emit("code_run", purpose=purpose, code=call["args"].get("code", ""),
                 attempt=calls)

            before = len(charts)
            output = run_python.invoke(call["args"])

            # Numbered from one, matching the [chart:N] markers synthesize will
            # place in the report.
            for offset, chart in enumerate(charts[before:]):
                emit("chart_ready", title=chart.get("title"),
                     format=chart.get("format"), index=before + offset + 1)

            # Models spend their whole budget exploring unless told what is
            # left. Stating it plainly after every call is what turns a
            # meandering inspection into inspect-then-plot.
            left = MAX_SANDBOX_CALLS - calls
            if left == 0:
                output += "\n\nThis was your last call. Stop now."
            elif not charts:
                output += (
                    f"\n\n{left} call(s) left, and no chart yet. Draw one now "
                    f"with what you have, or say there is nothing worth charting."
                )
            else:
                output += f"\n\n{left} call(s) left."

            messages.append(ToolMessage(content=output, tool_call_id=call["id"]))

        if calls >= MAX_SANDBOX_CALLS:
            log.info("sandbox budget (%d) spent", MAX_SANDBOX_CALLS)
            break

    # Cap what reaches the report regardless of how many the model produced.
    charts = charts[:MAX_CHARTS]
    log.info("visualize: %d call(s), %d chart(s)", calls, len(charts))
    return {"charts": charts}
