"""The code execution tool.

Built per run rather than declared at import, because the tool has to carry
that run's evidence with it. The tools execute in a thread pool where per-run
state does not propagate, so a factory closing over the data is the mechanism
that works — the same reason `keywords` is applied at dispatch rather than
inside the search tools.
"""

import logging

from langchain_core.tools import tool

from agent import sandbox_client

log = logging.getLogger(__name__)

# What the sandbox receives per finding. Far more than the model sees: the
# prompt caps a document at 8k characters, while code can regex a table out of
# forty thousand.
MAX_TEXT_CHARS = 60_000


def build_payload(findings: list[dict]) -> list[dict]:
    """Reshape findings for the sandbox.

    Structured results keep their structure. `market_data` flattens itself into
    prose for the model, which is fine to read and useless to compute with, so
    anything numeric is passed through as its own key.
    """
    payload = []
    for i, f in enumerate(findings, 1):
        if f.get("error"):
            continue
        item = {
            "i": i,
            "title": f.get("title") or f.get("claim"),
            "url": f.get("url"),
            "text": (f.get("snippet") or "")[:MAX_TEXT_CHARS],
        }
        for key in ("ticker", "currency", "data", "pages", "author",
                    "published_date", "score"):
            if f.get(key) is not None:
                item[key] = f[key]
        payload.append(item)
    return payload


def make_run_python(findings: list[dict], charts: list[dict]):
    """Build a run_python tool bound to this run's evidence.

    `charts` is appended to in place — the node that owns it collects whatever
    the model manages to produce, including from a call that later fails.
    """
    payload = build_payload(findings)

    @tool
    def run_python(code: str, purpose: str) -> str:
        """Run Python to analyse the evidence and draw charts.

        Every finding from this run is already loaded into a variable called
        `findings` — a list of dicts with `title`, `url` and `text`. Sources
        vary, so inspect the shape before assuming it: print keys and a sample
        first if you are unsure.

        pandas, numpy, plotly and matplotlib are available. There is no network
        access; everything you need is in `findings`.

        Call emit_chart(fig, title) to put a figure in the report. Prefer
        plotly — those charts are interactive for the reader. Whatever you
        print comes back to you, so print what you want to reason about.
        """
        log.info("run_python: %s", purpose)
        result = sandbox_client.execute(code, payload)

        produced = result.get("charts") or []
        charts.extend(produced)

        lines = []
        if result.get("stdout"):
            lines.append(f"Output:\n{result['stdout']}")
        if produced:
            titles = ", ".join(c.get("title") or "untitled" for c in produced)
            lines.append(f"Charts added to the report: {titles}")
        if result.get("error"):
            lines.append(f"Failed with {result['error']}:\n{result.get('stderr', '')}")
        elif result.get("stderr"):
            lines.append(f"Notes:\n{result['stderr']}")

        if not lines:
            lines.append(
                "The code ran and produced nothing — no output, no chart. "
                "Print something, or call emit_chart."
            )
        return "\n\n".join(lines)

    return run_python
