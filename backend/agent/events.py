"""Trace events emitted while the graph runs.

Nodes call emit() to report progress. LangGraph's stream writer forwards these
to whoever is consuming the run, so the API can stream them to the browser as
they happen rather than only after a node finishes.

Outside a graph run there is no writer; emit() then does nothing, so the CLI
and tests work unchanged.
"""

from datetime import datetime, timezone
from typing import Any

from langgraph.config import get_stream_writer


def emit(event: str, **data: Any) -> None:
    emit_via(capture(), event, **data)


def capture():
    """Grab the stream writer so worker threads can emit too.

    get_stream_writer() reads a context variable that is not propagated into
    threads, so a worker calling emit() directly would silently drop its
    events. The parallel sub-agents capture the writer on the main thread
    before they fan out, and emit through it.
    """
    try:
        return get_stream_writer()
    except Exception:  # noqa: BLE001 - not running inside a graph
        return None


def emit_via(writer, event: str, **data: Any) -> None:
    """Emit through an already-captured writer. Safe to call from any thread."""
    if writer is None:
        return
    writer({
        "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **data,
    })
