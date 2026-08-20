"""Real web search, backed by Tavily.

Deliberately keeps the same names, signatures and descriptions as the mocks it
replaces, so the agent's tool-selection behaviour is unchanged by the swap —
only the quality of what comes back differs.
"""

import logging
from typing import Any

from langchain_core.tools import tool
from tavily import TavilyClient

from config import settings

log = logging.getLogger(__name__)

MAX_RESULTS = 5

_client: TavilyClient | None = None


def _get_client() -> TavilyClient:
    global _client
    if _client is None:
        if not settings.tavily_api_key:
            raise ValueError("TAVILY_API_KEY is not set")
        _client = TavilyClient(api_key=settings.tavily_api_key)
    return _client


def _to_findings(response: dict) -> list[dict[str, Any]]:
    """Normalise a Tavily response into our finding shape."""
    findings = []
    for r in response.get("results", []):
        findings.append({
            "claim": r.get("title", "Untitled"),
            "snippet": (r.get("content") or "").strip(),
            "url": r.get("url", ""),
            "title": r.get("title", "Untitled"),
            "published_date": r.get("published_date"),
            "score": r.get("score"),
        })
    return findings


def _search(query: str, topic: str) -> list[dict[str, Any]]:
    """Run a search, returning an error finding rather than raising.

    A failed tool call must not end the run — the agent should see the failure,
    and can decide to retry, rephrase or work around it.
    """
    try:
        response = _get_client().search(
            query=query, topic=topic, max_results=MAX_RESULTS, search_depth="basic"
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the model, not swallowed
        log.warning("tavily %s search failed for %r: %s", topic, query, exc)
        return [{
            "claim": f"Search failed: {exc}",
            "snippet": "This tool call did not succeed. Consider rephrasing "
                       "the query or using a different tool.",
            "url": "",
            "title": "Tool error",
            "error": True,
        }]

    findings = _to_findings(response)
    log.info("tavily %s: %r -> %d results", topic, query, len(findings))
    return findings


@tool
def web_search(query: str) -> list[dict]:
    """Search the web for general information on any topic.

    The best default when you need broad background, definitions, analysis or
    opinion. Use it first unless the question clearly calls for a specialised
    tool. Returns several results with titles, URLs and snippets.
    """
    return _search(query, topic="general")


@tool
def news_search(query: str) -> list[dict]:
    """Search recent news articles for current events and breaking developments.

    Use when the question concerns something recent, ongoing or time-sensitive —
    policy announcements, market moves, company events. Not useful for
    background or historical context. Returns headlines with publication dates.
    """
    return _search(query, topic="news")
