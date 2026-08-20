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
    try:
        writer = get_stream_writer()
    except Exception:  # noqa: BLE001 - not running inside a graph
        return
    if writer is None:
        return
    writer({
        "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **data,
    })
