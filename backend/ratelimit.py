"""Per-IP rate limiting.

The deployed demo spends our own API key, so an unbounded endpoint is an
unbounded bill. This is a simple in-memory sliding window.

Caveat: state is per-instance. Cloud Run may run several instances, so the
effective limit is the configured limit times the instance count. That is
acceptable here — Gemini's free tier is the real hard ceiling. A shared store
(Redis, Firestore) would be needed for an exact global limit.
"""

import time
from collections import defaultdict, deque

WINDOW_SECONDS = 3600
MAX_RUNS_PER_WINDOW = 10

_hits: dict[str, deque] = defaultdict(deque)


def check(client_id: str) -> tuple[bool, int]:
    """Record an attempt. Returns (allowed, seconds_until_retry)."""
    now = time.monotonic()
    hits = _hits[client_id]

    while hits and now - hits[0] > WINDOW_SECONDS:
        hits.popleft()

    if len(hits) >= MAX_RUNS_PER_WINDOW:
        return False, int(WINDOW_SECONDS - (now - hits[0])) + 1

    hits.append(now)
    return True, 0
