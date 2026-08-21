"""Market data and company fundamentals, via yfinance.

Replaces the mock that returned fabricated figures. That mattered more than
most: a made-up share price reads exactly like a real one, so the agent could
state a fabricated number with full confidence.

Caveat worth knowing: yfinance is an unofficial client that reads Yahoo
Finance's public endpoints. It is free and needs no key, but Yahoo can change
those endpoints without notice, so this tool is the most likely of the four to
break one day. Failures return an error finding rather than raising, so the
agent can fall back to searching.
"""

import logging
from typing import Any

import yfinance as yf
from langchain_core.tools import tool

log = logging.getLogger(__name__)

SOURCE_URL = "https://finance.yahoo.com/quote/{symbol}"


def _error(query: str, message: str) -> list[dict]:
    return [
        {
            "claim": f"No market data for {query}",
            "snippet": f"{message} If this is a private company, an index or a "
            f"sector, market data will not exist for it — use web_search "
            f"instead.",
            "url": "",
            "title": "Market data unavailable",
            "error": True,
        }
    ]


def _money(value: Any, currency: str = "") -> str:
    """Format a large number the way a person would read it."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "n/a"
    suffix = f" {currency}".rstrip()
    for cutoff, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(n) >= cutoff:
            return f"{n / cutoff:.2f}{unit}{suffix}"
    return f"{n:,.2f}{suffix}"


def _num(value: Any, fmt: str = "{:.2f}") -> str:
    try:
        return fmt.format(float(value))
    except (TypeError, ValueError):
        return "n/a"


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _resolve(query: str) -> str | None:
    """Turn a company name into a ticker, if it is not one already."""
    try:
        results = yf.Search(query, max_results=5).quotes
    except Exception as exc:  # noqa: BLE001
        log.warning("ticker search failed for %r: %s", query, exc)
        return None

    for quote in results:
        # Prefer an equity on a US exchange; the same company often lists on
        # several, and the primary listing has the fullest data.
        if quote.get("quoteType") == "EQUITY" and quote.get("symbol"):
            return quote["symbol"]
    return results[0].get("symbol") if results else None


@tool
def market_data(company_or_ticker: str) -> list[dict]:
    """Look up share price and financial fundamentals for a public company.

    Use for questions about a specific listed company's valuation, share price,
    revenue, profitability or debt. Accepts a ticker (AAPL) or a company name
    (Apple). Only covers publicly traded companies — not private firms, sectors,
    indices or economies. Figures are the latest available from Yahoo Finance.
    """
    query = company_or_ticker.strip()
    if not query:
        return _error(query, "No company was given.")

    try:
        info = yf.Ticker(query).info
    except Exception:  # noqa: BLE001
        info = {}

    # A bad ticker returns a sparse dict rather than raising, so check for real
    # content before deciding the lookup worked.
    if not info.get("shortName") and not info.get("longName"):
        symbol = _resolve(query)
        if not symbol:
            return _error(query, f"Could not find a listed company matching {query!r}.")
        log.info("resolved %r -> %s", query, symbol)
        try:
            info = yf.Ticker(symbol).info
        except Exception as exc:  # noqa: BLE001
            return _error(query, f"Lookup failed: {exc}")
        if not info.get("shortName") and not info.get("longName"):
            return _error(query, f"No data available for {symbol}.")

    symbol = info.get("symbol") or query.upper()
    name = info.get("longName") or info.get("shortName") or symbol
    currency = info.get("currency", "")

    rows = [
        ("Sector", info.get("sector") or "n/a"),
        ("Industry", info.get("industry") or "n/a"),
        ("Price", f"{_num(info.get('currentPrice'))} {currency}".strip()),
        ("52-week range",
         f"{_num(info.get('fiftyTwoWeekLow'))} - {_num(info.get('fiftyTwoWeekHigh'))}"),
        ("Market cap", _money(info.get("marketCap"), currency)),
        ("P/E (trailing)", _num(info.get("trailingPE"))),
        ("P/E (forward)", _num(info.get("forwardPE"))),
        ("Revenue (TTM)", _money(info.get("totalRevenue"), currency)),
        ("Profit margin", _pct(info.get("profitMargins"))),
        ("Total debt", _money(info.get("totalDebt"), currency)),
        ("Dividend yield", _pct(info.get("dividendYield"))),
    ]
    table = "\n".join(f"{label}: {value}" for label, value in rows)

    summary = (info.get("longBusinessSummary") or "").strip()
    if len(summary) > 900:
        summary = summary[:900] + " [...]"

    body = f"{name} ({symbol}) — market data from Yahoo Finance\n\n{table}"
    if summary:
        body += f"\n\nBusiness: {summary}"

    # The formatted table above is for reading; this is for computing. Code in
    # the sandbox charts these directly rather than parsing them back out of
    # prose — a number re-read from text is a number that can be misread.
    numeric = {
        key: info.get(key)
        for key in (
            "currentPrice", "fiftyTwoWeekLow", "fiftyTwoWeekHigh", "marketCap",
            "trailingPE", "forwardPE", "totalRevenue", "profitMargins",
            "grossMargins", "operatingMargins", "totalDebt", "totalCash",
            "dividendYield", "beta", "freeCashflow", "revenueGrowth",
            "earningsGrowth", "returnOnEquity", "debtToEquity",
        )
        if isinstance(info.get(key), (int, float))
    }

    log.info("market data for %s (%s)", name, symbol)
    return [
        {
            "claim": f"Market data for {name} ({symbol})",
            "snippet": body,
            "url": SOURCE_URL.format(symbol=symbol),
            "title": f"{name} ({symbol}) — Yahoo Finance",
            "ticker": symbol,
            "currency": currency,
            "data": numeric,
        }
    ]
