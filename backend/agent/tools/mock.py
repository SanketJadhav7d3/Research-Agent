"""Mock tools.

Four distinct tools with different specialities, so the agent has a real choice
to make rather than one obvious option. Each is a LangChain tool: the docstring
is what the model reads when deciding whether to call it, so the descriptions
are prompt engineering, not documentation.

Sprint 3+ replaces each body with a real API. The names, signatures and
descriptions stay, so the agent's decision-making is unaffected by the swap.
"""

from typing import Any

from langchain_core.tools import tool

MOCK_NOTE = "[MOCK DATA — not a real source]"


def _finding(claim: str, snippet: str, url: str, title: str) -> dict[str, Any]:
    return {"claim": claim, "snippet": snippet, "url": url, "title": title}


@tool
def financial_data(ticker_or_company: str) -> list[dict]:
    """Look up market data and fundamentals for a public company.

    Use for share prices, valuation ratios, revenue, debt and regulatory
    filings. Takes a ticker symbol or company name. Only useful for publicly
    traded companies — not for sectors, indices or private firms.
    """
    return [
        _finding(
            f"{MOCK_NOTE} Financial metrics for {ticker_or_company}",
            f"{MOCK_NOTE} Price, P/E, revenue and debt figures for "
            f"'{ticker_or_company}'.",
            "https://example.com/financials",
            "Market Data Terminal",
        ),
    ]


@tool
def read_page(url: str) -> list[dict]:
    """Fetch and read the full text of a specific web page.

    Use when a search result looks important and the snippet is not enough, or
    when the user names a URL directly. Takes one URL and returns its cleaned
    text. Do not use it to search — you need a URL already.
    """
    return [
        _finding(
            f"{MOCK_NOTE} Full text extracted from {url}",
            f"{MOCK_NOTE} The complete article body from '{url}'.",
            url,
            "Full page content",
        ),
    ]


