"""Full-page reading via Jina AI Reader.

Prefixing a URL with https://r.jina.ai/ returns the page as clean markdown —
no navigation, ads or HTML noise, and no headless browser in our image.

Trade-off accepted in the spec: login-protected and some heavily JS-rendered
pages will not work. Those return an error finding the agent can route around.
"""

import logging

import httpx

from langchain_core.tools import tool

from config import settings

log = logging.getLogger(__name__)

JINA_ENDPOINT = "https://r.jina.ai/"
TIMEOUT_SECONDS = 45.0

# A full article can be many thousands of words. Truncate so one greedy page
# cannot crowd out the agent's reasoning or blow up token cost.
MAX_CHARS = 12_000


def _error(url: str, message: str) -> list[dict]:
    return [{
        "claim": f"Could not read {url}",
        "snippet": f"{message} Try a different source, or rely on the search "
                   f"snippet you already have.",
        "url": url,
        "title": "Page read failed",
        "error": True,
    }]


@tool
def read_page(url: str) -> list[dict]:
    """Fetch and read the full text of a specific web page.

    Use when a search result looks important and the snippet is not enough, or
    when the user names a URL directly. Takes one URL and returns its cleaned
    text. Do not use it to search — you need a URL already.
    """
    if not url.startswith(("http://", "https://")):
        return _error(url, "That is not a valid http(s) URL.")

    headers = {}
    if settings.jina_api_key:
        headers["Authorization"] = f"Bearer {settings.jina_api_key}"

    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True) as client:
            response = client.get(f"{JINA_ENDPOINT}{url}", headers=headers)
            response.raise_for_status()
            text = response.text
    except httpx.TimeoutException:
        log.warning("jina timeout for %s", url)
        return _error(url, f"The page took longer than {TIMEOUT_SECONDS:.0f}s to load.")
    except Exception as exc:  # noqa: BLE001 - surfaced to the model
        log.warning("jina failed for %s: %s", url, exc)
        return _error(url, f"Fetch failed: {exc}")

    truncated = len(text) > MAX_CHARS
    if truncated:
        text = text[:MAX_CHARS] + "\n\n[…truncated]"

    log.info("read %s -> %d chars%s", url, len(text), " (truncated)" if truncated else "")
    return [{
        "claim": f"Full text of {url}",
        "snippet": text,
        "url": url,
        "title": "Full page content",
        "truncated": truncated,
    }]
