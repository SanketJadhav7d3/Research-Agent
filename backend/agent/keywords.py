"""User-supplied keyword preferences for the search tools.

Two lists, both optional:

  include - terms the user wants searches biased towards
  exclude - terms whose results the user does not want to see

They are applied in the execute node rather than inside the tools themselves.
The tools run in a thread pool, and per-run state does not propagate into
worker threads; applying it at dispatch keeps everything in the calling thread
and makes the effect visible in the trace.

Worth being honest about the asymmetry: exclusion is enforced here, by
discarding results ourselves. Inclusion is only a hint — Tavily matches
semantically, so appending a term biases the ranking but guarantees nothing.
The UI wording reflects that.
"""

MAX_TERMS = 8
MAX_TERM_CHARS = 60

# Only the two general-purpose search tools take a free-text query that these
# make sense for. A page or PDF fetch is a specific address the model chose.
SEARCH_TOOLS = {"web_search", "news_search"}


def clean(terms: list[str] | None) -> list[str]:
    """Normalise a user-supplied term list.

    Trims, drops blanks and duplicates, and caps both the number of terms and
    the length of each so a pathological input cannot bloat every query.
    """
    out: list[str] = []
    seen: set[str] = set()
    for term in terms or []:
        if not term:
            continue
        t = " ".join(str(term).split())[:MAX_TERM_CHARS].strip()
        if not t or t.lower() in seen:
            continue
        seen.add(t.lower())
        out.append(t)
        if len(out) >= MAX_TERMS:
            break
    return out


def augment(query: str, include: list[str]) -> str:
    """Add the required terms to a search query.

    Terms the model already worked into the query are left out rather than
    repeated — a doubled term skews the search more than it helps.
    """
    if not include:
        return query
    lowered = query.lower()
    extra = [t for t in include if t.lower() not in lowered]
    return f"{query} {' '.join(extra)}" if extra else query


def blocked(finding: dict, exclude: list[str]) -> bool:
    """Whether a search result mentions an excluded term.

    Matches on title, snippet and URL, case-insensitively. Substring matching
    is deliberate: excluding "crypto" should also drop "cryptocurrency", which
    is what a user typing that term almost certainly means.
    """
    if not exclude:
        return False
    haystack = " ".join([
        finding.get("title") or "",
        finding.get("claim") or "",
        finding.get("snippet") or "",
        finding.get("url") or "",
    ]).lower()
    return any(t.lower() in haystack for t in exclude)


def filter_results(results: list[dict], exclude: list[str]) -> tuple[list[dict], int]:
    """Drop excluded results, returning what survived and how many went.

    Error findings are always kept. They carry no evidence to filter, and
    swallowing one would leave the model staring at an empty result with no
    indication that its tool call actually failed.
    """
    if not exclude:
        return results, 0
    kept = [r for r in results if r.get("error") or not blocked(r, exclude)]
    return kept, len(results) - len(kept)


def brief(include: list[str], exclude: list[str]) -> str:
    """The instruction fragment describing these preferences to the model."""
    if not include and not exclude:
        return ""
    lines = ["\nThe user has set search preferences:"]
    if include:
        lines.append(
            "- Focus on: " + ", ".join(include)
            + ". Work these into your queries where they fit naturally."
        )
    if exclude:
        lines.append(
            "- Avoid: " + ", ".join(exclude)
            + ". Results mentioning these are filtered out before you see "
              "them, so phrasing queries around them wastes calls."
        )
    return "\n".join(lines) + "\n"
