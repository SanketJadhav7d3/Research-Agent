"""PDF reading via PyMuPDF.

Academic papers, regulatory filings and industry reports are usually PDFs, and
search results routinely point at them. Without this the agent can only read the
landing page that links to a paper, never the paper.

Note on licensing: PyMuPDF is AGPL-3.0. Fine for this open-source project;
swapping to pypdf (BSD) would mean changing only this file, at the cost of
noticeably worse extraction on complex layouts.
"""

import logging
import re

import httpx
import pymupdf
from langchain_core.tools import tool

log = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT = 45.0

# A single filing can run to hundreds of pages and tens of megabytes. Cap both
# the download and the extracted text so one document cannot exhaust the
# context window or stall a run.
MAX_BYTES = 25 * 1024 * 1024
MAX_PAGES = 40
MAX_CHARS = 14_000


def _error(source: str, message: str) -> list[dict]:
    return [
        {
            "claim": f"Could not read PDF at {source}",
            "snippet": f"{message} Try another source, or use the search snippet "
            f"you already have.",
            "url": source,
            "title": "PDF read failed",
            "error": True,
        }
    ]


def _clean(text: str) -> str:
    """Tidy extracted text.

    PDF extraction leaves hyphenated line breaks and hard-wrapped lines that
    make the prose harder for the model to read than it needs to be.
    """
    text = re.sub(r"-\n(\w)", r"\1", text)  # rejoin hyphenated words
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


@tool
def read_pdf(url: str) -> list[dict]:
    """Download and read the text of a PDF document.

    Use for academic papers, regulatory filings, whitepapers and reports —
    anything whose URL ends in .pdf or that a search result identifies as a PDF.
    Returns the document's text along with its title, author and page count.
    Use read_page instead for ordinary web pages.
    """
    if not url.startswith(("http://", "https://")):
        return _error(url, "That is not a valid http(s) URL.")

    try:
        with httpx.Client(timeout=DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            data = response.content
    except httpx.TimeoutException:
        log.warning("pdf download timed out: %s", url)
        return _error(url, f"Download exceeded {DOWNLOAD_TIMEOUT:.0f}s.")
    except Exception as exc:  # noqa: BLE001 - surfaced to the model
        log.warning("pdf download failed for %s: %s", url, exc)
        return _error(url, f"Download failed: {exc}")

    # PyMuPDF will cheerfully parse HTML and other formats, producing a bogus
    # "document" from a web page. Every real PDF starts with %PDF, so check that
    # rather than trusting the URL or the server's content-type.
    if not data[:1024].lstrip().startswith(b"%PDF"):
        log.info("not a pdf: %s", url)
        return _error(
            url,
            "That URL is not a PDF (no %PDF header). Use read_page for web pages.",
        )

    if len(data) > MAX_BYTES:
        return _error(
            url, f"The file is {len(data) / 1_048_576:.0f}MB, above the "
            f"{MAX_BYTES // 1_048_576}MB limit."
        )

    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 - malformed or not actually a PDF
        log.warning("pdf parse failed for %s: %s", url, exc)
        return _error(url, f"Not a readable PDF: {exc}")

    with doc:
        if doc.is_encrypted and not doc.authenticate(""):
            return _error(url, "The PDF is password protected.")

        meta = doc.metadata or {}
        total_pages = doc.page_count
        pages = []
        for i in range(min(total_pages, MAX_PAGES)):
            pages.append(doc.load_page(i).get_text())

    text = _clean("\n\n".join(pages))
    if not text:
        return _error(
            url,
            "No extractable text — the PDF is probably a scan, which would need OCR.",
        )

    truncated = len(text) > MAX_CHARS or total_pages > MAX_PAGES
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n\n[...truncated]"

    title = (meta.get("title") or "").strip() or url.rsplit("/", 1)[-1]
    author = (meta.get("author") or "").strip()

    log.info(
        "read pdf %s -> %d/%d pages, %d chars%s",
        url, min(total_pages, MAX_PAGES), total_pages, len(text),
        " (truncated)" if truncated else "",
    )

    header = f"{title}"
    if author:
        header += f" — {author}"
    header += f" ({total_pages} pages)"

    return [
        {
            "claim": f"PDF: {title}",
            "snippet": f"{header}\n\n{text}",
            "url": url,
            "title": title,
            "author": author or None,
            "pages": total_pages,
            "truncated": truncated,
        }
    ]
