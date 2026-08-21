"""FastAPI application entrypoint.

Exposes the agent as a streaming endpoint: the client posts a goal and receives
the agent's trace as Server-Sent Events while the run is still in progress.
"""

import json
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import ratelimit
from agent import keywords
from agent.graph import graph
from agent.llm import get_model, SUPPORTED_PROVIDERS
from agent.schemas import ImprovedPrompt
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


class ModelChoice(BaseModel):
    """Optional bring-your-own-key. Used for this request only; never stored,
    never logged. Omit to use the server's default provider."""

    provider: str | None = None
    model: str | None = None
    api_key: str | None = None


class ResearchRequest(ModelChoice):
    goal: str = Field(min_length=3, max_length=2000)
    max_iterations: int = Field(default=MAX_ITERATIONS_CAP, ge=1)

    # Search preferences. Both are sanitised and capped by agent.keywords
    # before use, so an oversized list cannot bloat every query.
    include_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)


class ImproveRequest(ModelChoice):
    goal: str = Field(min_length=3, max_length=2000)


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


IMPROVE_INSTRUCTION = (
    "You are helping someone sharpen a research question before an agent "
    "researches it.\n\n"
    "Rewrite the question below so it is clearer, more specific and easier to "
    "research well. Make the scope, timeframe and basis of comparison explicit "
    "where the wording leaves them vague.\n\n"
    "Critical constraint: keep the user's actual subject and intent. Do NOT "
    "invent constraints they did not state — no dates, regions, industries, "
    "company names or metrics they did not mention. If the question is already "
    "clear, return it close to unchanged with an empty change list. Narrowing "
    "a question to something the user never asked is worse than leaving it "
    "broad.\n\n"
    "Keep the rewrite to a couple of sentences at most.\n\n"
    "Question: "
)


@app.post("/improve-prompt")
async def improve_prompt(req: ImproveRequest, request: Request) -> dict:
    """Rewrite a research question to be clearer and more specific.

    One model call, so this returns a plain JSON body rather than a stream. The
    caller decides whether to accept the rewrite; nothing is researched here.
    """
    client_id = request.client.host if request.client else "unknown"
    if not req.api_key:
        allowed, retry_after = ratelimit.check(client_id)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit reached. Try again in {retry_after}s, or "
                       f"supply your own API key.",
            )

    model = get_model(
        provider=req.provider or None,
        model=req.model or None,
        api_key=req.api_key or None,
    )
    try:
        # The model call blocks, so keep it off the event loop.
        result = await run_in_threadpool(
            model.with_structured_output(ImprovedPrompt).invoke,
            IMPROVE_INSTRUCTION + req.goal,
        )
    except Exception as exc:  # noqa: BLE001 - reported to the client
        log.exception("prompt improvement failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    improved = (result.improved or "").strip()
    if not improved:
        raise HTTPException(status_code=502, detail="The model returned nothing.")

    log.info("improved prompt: %r -> %r", req.goal[:60], improved[:60])
    return {"improved": improved, "changes": result.changes}


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
                    "include_keywords": keywords.clean(req.include_keywords),
                    "exclude_keywords": keywords.clean(req.exclude_keywords),
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
