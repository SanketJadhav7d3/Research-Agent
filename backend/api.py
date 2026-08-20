"""FastAPI application entrypoint.

Exposes the agent as a streaming endpoint: the client posts a goal and receives
the agent's trace as Server-Sent Events while the run is still in progress.
"""

import json
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import ratelimit
from agent.graph import graph
from agent.llm import SUPPORTED_PROVIDERS
from config import MAX_ITERATIONS_CAP, settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="Research Agent API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ResearchRequest(BaseModel):
    goal: str = Field(min_length=3, max_length=2000)
    max_iterations: int = Field(default=MAX_ITERATIONS_CAP, ge=1)

    # Optional bring-your-own-key. Used for this request only; never stored,
    # never logged. Omit to use the server's default provider.
    provider: str | None = None
    model: str | None = None
    api_key: str | None = None


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe. Used by Docker Compose and Cloud Run health checks."""
    return {"status": "ok"}


@app.get("/providers")
async def providers() -> dict:
    """What the UI needs to render a model picker."""
    return {
        "default": settings.llm_provider,
        "default_model": settings.llm_model,
        "supported": sorted(SUPPORTED_PROVIDERS),
        "byok_required": [
            p for p in sorted(SUPPORTED_PROVIDERS) if p != settings.llm_provider
        ],
    }


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.post("/research")
async def research(req: ResearchRequest, request: Request) -> StreamingResponse:
    """Run the agent, streaming its trace as it happens."""
    client_id = request.client.host if request.client else "unknown"

    # A caller supplying their own key spends their own quota, so it does not
    # count against our limit.
    if not req.api_key:
        allowed, retry_after = ratelimit.check(client_id)
        if not allowed:
            async def limited():
                yield _sse("error", {
                    "message": "Rate limit reached. Try again later, or supply "
                               "your own API key to bypass this limit.",
                    "retry_after_seconds": retry_after,
                })
            return StreamingResponse(limited(), media_type="text/event-stream")

    # Client-supplied iteration counts are clamped, never trusted.
    max_iterations = min(req.max_iterations, MAX_ITERATIONS_CAP)

    async def stream():
        try:
            async for chunk in graph.astream(
                {
                    "goal": req.goal,
                    "iteration": 0,
                    "max_iterations": max_iterations,
                    "tool_calls": [],
                    "findings": [],
                    "provider": req.provider or "",
                    "model": req.model or "",
                    "api_key": req.api_key or "",
                },
                stream_mode="custom",
            ):
                yield _sse(chunk.get("event", "message"), chunk)
        except Exception as exc:  # noqa: BLE001 - reported to the client
            log.exception("research run failed")
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
