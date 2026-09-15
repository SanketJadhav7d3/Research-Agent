"""The five graph nodes.

Each takes the current state and returns only the keys it changed; LangGraph
merges the result. Nodes read their model through get_model() so the provider
stays swappable.
"""

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from config import (
    MAX_MODEL_TURNS_CAP,
    MAX_PARALLEL_AGENTS,
    MAX_TOOL_CALLS_PER_AGENT,
    MAX_TOOL_CALLS_PER_ROUND,
    MAX_TOOL_CALLS_TOTAL,
    MAX_SANDBOX_CALLS,
    MAX_CHARTS,
)
from agent import keywords, sandbox_client
from agent.events import capture, emit, emit_via
from agent.llm import get_model, invoke_with_retry
from agent.schemas import ClarifiedGoal, Reflection, ResearchPlan
from agent.state import AgentState
from agent.tools import ALL_TOOLS, TOOLS_BY_NAME
from agent.tools.code import build_payload, make_run_python

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
    result = invoke_with_retry(
        _model(state).with_structured_output(ClarifiedGoal),
        "You are scoping a research task. Restate the goal below precisely: make "
        "the scope, timeframe and subject explicit, and resolve any ambiguity. "
        "List the assumptions you had to make.\n\n"
        f"Goal: {state['goal']}",
        label="clarify",
    )
    log.info("clarified: %s", result.clarified_goal)
    return {
        "clarified_goal": result.clarified_goal,
        "assumptions": result.assumptions,
    }


def plan(state: AgentState) -> dict:
    """Break the goal into independently researchable sub-questions."""
    emit("node_start", node="plan")
    result = invoke_with_retry(
        _model(state).with_structured_output(ResearchPlan),
        "Break this research goal into 2-3 concrete sub-questions. Each must be "
        "independently researchable, and together they must fully cover the "
        "goal. Do not answer them.\n\n"
        "If the goal is evaluative or debatable (a risk, a decision, a "
        "comparison, an opinion-laden topic), frame the sub-questions around "
        "distinct perspectives — e.g. one surfacing the positive case, one the "
        "negative or risk case, and one neutral/contextual factors — so the "
        "research doesn't lean one-sided. If the goal is purely factual (a "
        "number, a date, a definition, a status) that framing doesn't apply — "
        "just split it into its 2-3 most useful factual angles instead.\n\n"
        f"Goal: {state['clarified_goal']}",
        label="plan",
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


SUBAGENT_SYSTEM = (
    "You are one of several research agents working on the same goal in "
    "parallel. You own exactly one sub-question, given below.\n\n"
    "Research only your sub-question. The others are being covered by other "
    "agents at this moment — evidence you gather outside your remit is "
    "duplicated work, and evidence you skip inside it is a hole nobody else "
    "will fill.\n\n"
    "You have tools available. Decide for yourself which to use and in what "
    "order.\n\n"
    "If the goal names a specific URL, fetch it — read_pdf for a PDF, "
    "read_page otherwise. Searching for a document you were handed the "
    "address of wastes a call and returns worse evidence than the source "
    "itself.\n\n"
    "Search snippets are short and often superficial. When a result looks "
    "central to your sub-question, open it rather than relying on the "
    "preview.\n\n"
    "Call tools in parallel when the queries are independent. Your tool budget "
    "is small and shared with the other agents — spend it on your own "
    "sub-question. Stop calling tools once you have enough evidence, then "
    "summarise in two sentences what you found and what is still missing."
)


class _Shared:
    """Cross-agent bookkeeping for one Execute round.

    The workers run concurrently and would otherwise each rediscover the same
    pages: sub-questions on one goal overlap heavily, and two agents issuing
    near-identical searches is the obvious failure mode of fanning out. One
    lock-guarded set of seen calls and URLs makes the first agent to reach a
    source the only one that pays for it.
    """

    def __init__(self, tool_calls: list[dict], findings: list[dict], budget: int):
        self.lock = threading.Lock()
        self.seen_calls = {
            _call_key(c["tool"], c.get("input") or {}) for c in tool_calls
        }
        self.seen_urls = {f.get("url") for f in findings if f.get("url")}
        self.budget = budget          # total tool calls left this round
        self.spent = 0

    def claim(self, tool_name: str, args: dict) -> str | None:
        """Reserve one tool call. Returns None if it is a repeat or unaffordable.

        Claiming and recording happen under the same lock, so two agents racing
        on the same URL cannot both be told they are first.
        """
        with self.lock:
            if self.spent >= self.budget:
                return "budget"
            key = _call_key(tool_name, args)
            if key in self.seen_calls:
                return "repeat"
            self.seen_calls.add(key)
            self.spent += 1
            return None

    def fresh(self, results: list[dict]) -> list[dict]:
        """Filter to results whose URL no agent has recorded yet."""
        with self.lock:
            out = []
            for r in results:
                url = r.get("url")
                if url and url in self.seen_urls:
                    continue
                if url:
                    self.seen_urls.add(url)
                out.append(r)
            return out


def _agent_brief(state: AgentState, question: str) -> str:
    """The brief handed to a single sub-agent."""
    prefs = keywords.brief(
        state.get("include_keywords") or [], state.get("exclude_keywords") or []
    )
    context = (
        f"Overall research goal (for context only): {state['clarified_goal']}\n\n"
        f"YOUR SUB-QUESTION — research only this:\n{question}"
    )
    if state.get("iteration", 0) == 0:
        return context + prefs

    # A later round exists because Reflect judged the evidence thin, so say so
    # and name what has already been tried — otherwise the agent reissues the
    # searches that already failed to answer the question.
    tried = [
        str(v)
        for c in state.get("tool_calls", [])
        for v in (c.get("input") or {}).values()
    ]
    return (
        context
        + f"\n\nThis is a follow-up round. The earlier research scored "
          f"{state.get('confidence', 0):.0%} confidence. "
          f"{state.get('confidence_reason', '')}\n\n"
          "Queries already tried across all agents — do not repeat them. "
          "Rephrase, narrow, or approach from a different angle:\n"
        + "\n".join(f"- {t}" for t in tried[-15:])
        + prefs
    )


def _research_one(
    state: AgentState, question: str, label: str, shared: _Shared, writer
) -> tuple[list[dict], list[dict], bool]:
    """One sub-agent: researches a single sub-question to exhaustion.

    Returns its own tool calls and findings rather than mutating shared state,
    so a worker that fails takes nothing down with it. Runs on a worker thread,
    hence the passed-in `writer` — see events.capture().
    """
    model = _model(state).bind_tools(ALL_TOOLS)
    messages: list = [
        SystemMessage(SUBAGENT_SYSTEM),
        HumanMessage(_agent_brief(state, question)),
    ]

    include = state.get("include_keywords") or []
    exclude = state.get("exclude_keywords") or []
    tool_calls: list[dict] = []
    findings: list[dict] = []
    spent = 0
    stopped_early = False

    emit_via(writer, "subagent_start", agent=label, question=question)

    for turn in range(MAX_MODEL_TURNS_CAP):
        try:
            response = invoke_with_retry(model, messages, label=label)
        except Exception as exc:  # noqa: BLE001 - one agent must not sink the round
            log.warning("%s: model call failed: %s", label, exc)
            stopped_early = True
            break
        messages.append(response)

        if not response.tool_calls:
            log.info("%s finished after %d turn(s)", label, turn + 1)
            break

        runnable = []
        for call in response.tool_calls:
            if spent >= MAX_TOOL_CALLS_PER_AGENT:
                stopped_early = True
                break

            tool = TOOLS_BY_NAME.get(call["name"])
            if tool is None:
                # Shouldn't happen, but a hallucinated name must not crash the run.
                log.warning("%s: unknown tool %r", label, call["name"])
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

            refused = shared.claim(call["name"], call["args"])
            if refused == "budget":
                stopped_early = True
                messages.append(ToolMessage(
                    content="The shared tool budget for this round is spent. "
                            "Stop calling tools and summarise what you have.",
                    tool_call_id=call["id"],
                ))
                break
            if refused == "repeat":
                log.info("%s: skipping repeat: %s(%s)", label, call["name"], call["args"])
                emit_via(writer, "tool_skipped", agent=label, tool=call["name"],
                         input=call["args"],
                         reason="already fetched by another agent in this run")
                messages.append(ToolMessage(
                    content="Another agent already made this exact call in this "
                            "run, so it was skipped. Try a different query or "
                            "angle rather than repeating it.",
                    tool_call_id=call["id"],
                ))
                continue

            spent += 1
            log.info("%s: tool: %s(%s)", label, call["name"], call["args"])
            emit_via(writer, "tool_call", agent=label, tool=call["name"],
                     input=call["args"])
            runnable.append((call, tool))

        if runnable:
            with ThreadPoolExecutor(max_workers=len(runnable)) as pool:
                futures = {
                    pool.submit(copy_context().run, t.invoke, c["args"]): c
                    for c, t in runnable
                }
                outcomes = []
                for future in as_completed(futures):
                    call = futures[future]
                    try:
                        outcomes.append((call, future.result()))
                    except Exception as exc:  # noqa: BLE001 - reported to the model
                        log.warning("%s: tool %s raised: %s", label, call["name"], exc)
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
                        log.info("%s: excluded %d result(s)", label, dropped)
                        emit_via(writer, "results_filtered", agent=label,
                                 tool=call["name"], dropped=dropped, terms=exclude)

                emit_via(
                    writer,
                    "tool_result",
                    agent=label,
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
                    "agent": label,
                })
                findings.extend(shared.fresh(results))
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
            break
    else:
        stopped_early = True
        log.warning("%s: model turn cap (%d) reached", label, MAX_MODEL_TURNS_CAP)

    emit_via(writer, "subagent_done", agent=label, question=question,
             tool_calls=len(tool_calls), findings=len(findings))
    return tool_calls, findings, stopped_early


def execute(state: AgentState) -> dict:
    """Fan out one sub-agent per sub-question, then merge what they found.

    Each worker owns a single sub-question and its own context window, so one
    agent's long PDF cannot crowd another's evidence out of the prompt, and
    the sub-questions genuinely progress at the same time rather than in
    sequence. What stays shared is only what must be: the dedup sets and the
    round's tool budget.

    Within its own remit each worker is still the free agent Execute always
    was — it chooses its tools, its order, and when it has enough.
    """
    emit("node_start", node="execute")

    tool_calls = list(state.get("tool_calls", []))
    findings = list(state.get("findings", []))

    # This round's questions: the plan first time round, the gaps Reflect
    # identified thereafter.
    gaps = state.get("gaps") or []
    questions = (
        state["plan"] if state.get("iteration", 0) == 0 or not gaps else gaps
    )
    questions = questions[:MAX_PARALLEL_AGENTS]

    # Budget for this round: the per-round allowance, or whatever remains of the
    # overall ceiling, whichever is smaller. Shared across the workers.
    budget = min(MAX_TOOL_CALLS_PER_ROUND, MAX_TOOL_CALLS_TOTAL - len(tool_calls))
    shared = _Shared(tool_calls, findings, budget)

    emit("fanout", agents=len(questions), questions=questions, budget=budget)
    log.info("fanning out %d sub-agent(s), budget %d", len(questions), budget)

    # The stream writer is a context variable and does not cross into threads,
    # so capture it here and hand it to each worker.
    writer = capture()
    stopped_early = False

    with ThreadPoolExecutor(max_workers=max(1, len(questions))) as pool:
        # Each worker runs inside its own copy of this thread's context.
        # LangChain reads its runnable config from a context variable, which is
        # not inherited by a new thread — without this every worker dies on
        # "Called get_config outside of a runnable context" before its first
        # tool call. The copy must be per worker: a single Context object
        # cannot be entered by two threads at once.
        futures = {
            pool.submit(
                copy_context().run,
                _research_one, state, q, f"agent-{i}", shared, writer,
            ): i
            for i, q in enumerate(questions, 1)
        }
        results: list[tuple[int, tuple]] = []
        for future in as_completed(futures):
            i = futures[future]
            try:
                results.append((i, future.result()))
            except Exception as exc:  # noqa: BLE001 - a dead worker loses its
                # own findings, not the round's
                log.warning("agent-%d failed: %s", i, exc)
                stopped_early = True

    # Merge in sub-question order, not completion order, so the evidence list
    # and the trace read the same way on every run.
    for _, (agent_calls, agent_findings, agent_stopped) in sorted(results):
        tool_calls.extend(agent_calls)
        findings.extend(agent_findings)
        stopped_early = stopped_early or agent_stopped

    log.info(
        "merged %d agent(s): %d new call(s), %d finding(s) total",
        len(results), shared.spent, len(findings),
    )
    emit("merged", agents=len(results), tool_calls=len(tool_calls),
         findings=len(findings))

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
    result = invoke_with_retry(
        _model(state).with_structured_output(Reflection),
        "Assess honestly whether the evidence below answers the research goal. "
        "Be critical: score low if sources are thin, irrelevant or fabricated. "
        "Note that placeholder or mock evidence does not genuinely answer "
        "anything.\n\n"
        f"Goal: {state['clarified_goal']}\n\n"
        f"Sub-questions:\n" + "\n".join(f"- {q}" for q in state["plan"]) + "\n\n"
        f"Evidence:\n{evidence}",
        label="reflect",
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

    response = invoke_with_retry(
        _model(state),
        "Write a markdown research report answering the goal, using only the "
        "evidence below. Cite sources inline as [1], [2] matching the list. Do "
        "not invent facts. State limitations plainly where the evidence is weak "
        "or is placeholder data. Do not include a sources section — it is "
        "appended for you.\n\n"
        f"Goal: {state['clarified_goal']}\n\n"
        f"Confidence: {state['confidence']:.2f} ({state['confidence_reason']})\n\n"
        f"Evidence:\n{evidence}\n\n"
        f"Sources:\n{numbered}"
        f"{chart_brief}",
        label="synthesize",
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

    Enumerated over the payload the sandbox will actually receive, not over the
    raw findings: build_payload drops failed tool calls, so counting positions
    here independently makes every index quoted below wrong by the number of
    failures that preceded it.
    """
    payload = build_payload(state["findings"])
    lines = []
    structured = 0
    for pos, item in enumerate(payload):
        note = ""
        # Naming the keys — never the values — is what removes the excuse to
        # print the data and then retype it. The model can index straight in.
        if isinstance(item.get("data"), dict) and item["data"]:
            structured += 1
            note = f"  -> findings[{pos}]['data'] has: {', '.join(sorted(item['data']))}"
        elif item.get("pages"):
            note = f"  -> {item['pages']}pp document, figures are in ['text']"
        lines.append(f"[{pos + 1}] {item['title']}" + (f"\n{note}" if note else ""))

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
        response = invoke_with_retry(model, messages, label="visualize")
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
