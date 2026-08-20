"""Stand-in for the real tools.

Returns plausible, clearly-labelled fake findings so the graph, the prompts and
the state plumbing can be exercised without any external API. Sprint 3 replaces
this with Tavily search behind the same shape: a query in, a list of findings
out, each carrying its source.
"""

from typing import Any

FAKE_SOURCES = [
    ("https://example.com/analysis", "Industry Analysis Report"),
    ("https://example.org/research", "Independent Research Brief"),
    ("https://example.net/data", "Statistical Overview"),
]


def mock_search(query: str, limit: int = 3) -> list[dict[str, Any]]:
    """Return fabricated findings for a sub-question."""
    return [
        {
            "claim": f"[MOCK] Finding {i + 1} relevant to: {query}",
            "snippet": (
                f"[MOCK DATA — not real] A source discussing '{query}', included "
                f"so the agent has something concrete to reason over."
            ),
            "url": url,
            "title": title,
            "query": query,
        }
        for i, (url, title) in enumerate(FAKE_SOURCES[:limit])
    ]
